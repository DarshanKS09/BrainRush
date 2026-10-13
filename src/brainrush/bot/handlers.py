"""Telegram command handlers wired to the service layer.

Each handler receives a per-update `AsyncSession` (see `DbSessionMiddleware`)
and delegates persistence to services, which own their transactions. Game rules
live in `brainrush.game`; handlers only orchestrate. Unimplemented features
answer with honest coming-soon messages instead of fabricated data.
"""
from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from sqlalchemy.ext.asyncio import AsyncSession

from brainrush.db.errors import ConflictError, NotFoundError
from brainrush.game import number_guessing as guessing
from brainrush.game.store import ActiveGame, ActiveGameStore
from brainrush.services.games import GameSessionService
from brainrush.services.profiles import ProfileService
from brainrush.services.users import UserService

log = logging.getLogger("brainrush.bot")
router = Router()

GAME_TYPE_NUMBER_GUESSING = "number_guessing"

store = ActiveGameStore()

# Set once at startup via configure_webapp(); empty means "not configured",
# in which case commands work fully but show no Mini App button. Opening the
# Mini App requires a valid HTTPS URL configured with Telegram first.
WEBAPP_URL = ""


def configure_webapp(url: str) -> None:
    global WEBAPP_URL
    WEBAPP_URL = (url or "").strip()


def _webapp_button(text: str) -> InlineKeyboardMarkup | None:
    if not WEBAPP_URL:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, web_app=WebAppInfo(url=WEBAPP_URL))]
        ]
    )

_FRIENDLY_FAILURE = (
    "Something went wrong on our side. Please try again in a moment."
)
_NO_USER = "I can only help in a personal chat. Please message me directly."
_NO_ACTIVE_GAME = (
    "You don't have an active game right now. Send /play to start one."
)

HELP_TEXT = (
    "<b>BrainRush commands</b>\n"
    "/start - Register and see what's available\n"
    "/help - Show this help\n"
    "/profile - Show your level, XP and stats\n"
    "/games - List games (and what's coming soon)\n"
    "/play - Start a Number Guessing game\n"
    "/cancel - Abandon your active game (no XP)\n"
    "/leaderboard - Top players (coming soon)\n"
    "/daily - Daily rewards (coming soon)\n\n"
    "Tip: open the BrainRush Mini App from the buttons on /start, /games "
    "or /profile for the visual arcade with keypad controls."
)

GAMES_TEXT = (
    "<b>Available games</b>\n"
    "- Number Guessing (playable now! Send /play)\n"
    "- Quiz Rush (coming soon)\n"
    "- Memory Match (coming soon)"
)

LEADERBOARD_TEXT = (
    "The leaderboard is coming soon. Once more games launch, top players "
    "will show up here. Nothing to display yet - no rankings invented."
)

DAILY_TEXT = (
    "Daily rewards are coming soon. Check back after more games launch - "
    "no rewards to claim yet."
)


def _actor(message: Message) -> tuple[int, str | None, str] | None:
    """Return (telegram_id, username_or_None, display_name) or None."""
    user = message.from_user
    if user is None:
        return None
    username = user.username if user.username else None
    display = user.full_name.strip() if user.full_name and user.full_name.strip() else "there"
    return user.id, username, display


async def _safe_answer(
    message: Message, text: str, reply_markup: InlineKeyboardMarkup | None = None
) -> None:
    await message.answer(text, reply_markup=reply_markup)


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession) -> None:
    actor = _actor(message)
    if actor is None:
        await _safe_answer(message, _NO_USER)
        return
    telegram_id, username, display = actor
    try:
        user_service = UserService(session)
        await user_service.get_or_register(
            telegram_id=telegram_id, username=username, display_name=display
        )
    except Exception:
        log.error("cmd_start failed", exc_info=True)
        await _safe_answer(message, _FRIENDLY_FAILURE)
        return
    await _safe_answer(
        message,
        f"Welcome to BrainRush, {html.escape(display)}!\n"
        "Your profile is ready. Open the Mini App for the full arcade "
        "experience, or keep playing here.\n\n" + HELP_TEXT,
        reply_markup=_webapp_button("Open BrainRush"),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await _safe_answer(message, HELP_TEXT)


@router.message(Command("profile"))
async def cmd_profile(message: Message, session: AsyncSession) -> None:
    actor = _actor(message)
    if actor is None:
        await _safe_answer(message, _NO_USER)
        return
    telegram_id, username, display = actor
    try:
        user_service = UserService(session)
        profile_service = ProfileService(session)
        user, _profile = await user_service.get_or_register(
            telegram_id=telegram_id, username=username, display_name=display
        )
        stats = await profile_service.get_stats(user_id=user.id)
    except NotFoundError:
        await _safe_answer(message, "No profile found yet. Send /start first.")
        return
    except Exception:
        log.error("cmd_profile failed", exc_info=True)
        await _safe_answer(message, _FRIENDLY_FAILURE)
        return
    await _safe_answer(
        message,
        f"<b>{html.escape(display)}'s profile</b>\n"
        f"Level: {stats.current_level}\n"
        f"XP: {stats.total_xp}\n"
        f"Games played: {stats.games_played}\n"
        f"Wins: {stats.wins}\n"
        f"Losses: {stats.losses}\n"
        f"Current streak: {stats.current_streak}\n"
        f"Longest streak: {stats.longest_streak}",
        reply_markup=_webapp_button("Open Dashboard"),
    )


@router.message(Command("games"))
async def cmd_games(message: Message) -> None:
    await _safe_answer(
        message, GAMES_TEXT, reply_markup=_webapp_button("Open Game Lobby")
    )


@router.message(Command("play"))
async def cmd_play(message: Message, session: AsyncSession) -> None:
    actor = _actor(message)
    if actor is None:
        await _safe_answer(message, _NO_USER)
        return
    if WEBAPP_URL:
        # Visual Mini App is configured: route there instead of silently
        # starting the legacy text game. Return before any session/secret/
        # store side effects so the text game is never half-started.
        await _safe_answer(
            message,
            "Number Guessing lives in the BrainRush Mini App now — visual "
            "keypad, 3 difficulties, animations, and instant XP.\n\n"
            "Tap below to play!",
            reply_markup=_webapp_button("▶ Play in Mini App"),
        )
        return
    telegram_id, username, display = actor
    try:
        user, _ = await UserService(session).get_or_register(
            telegram_id=telegram_id, username=username, display_name=display
        )
        game_service = GameSessionService(session)
        async with store.lock_for(user.id):
            active = store.get(user.id)
            if active is not None and not active.game.finished:
                await _safe_answer(
                    message,
                    f"You're already playing! {active.game.attempts_left} "
                    f"guess(es) left. Keep guessing, or /cancel to give up.",
                )
                return
            if active is not None:
                store.remove(user.id)
            await game_service.abandon_stale_sessions(user_id=user.id)
            db_row = await game_service.start_session(
                user_id=user.id, game_type=GAME_TYPE_NUMBER_GUESSING
            )
            secret = guessing.roll_secret(guessing.DEFAULT_CONFIG)
            game = guessing.NumberGuessingGame(
                secret=secret, config=guessing.DEFAULT_CONFIG
            )
            store.put(
                ActiveGame(
                    user_id=user.id,
                    session_id=db_row.id,
                    game_type=GAME_TYPE_NUMBER_GUESSING,
                    game=game,
                )
            )
    except Exception:
        log.error("cmd_play failed", exc_info=True)
        await _safe_answer(message, _FRIENDLY_FAILURE)
        return
    cfg = guessing.DEFAULT_CONFIG
    await _safe_answer(
        message,
        f"I'm thinking of a number from {cfg.min_value} to {cfg.max_value}.\n"
        f"You have {cfg.max_attempts} guesses. Send your first guess!",
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, session: AsyncSession) -> None:
    actor = _actor(message)
    if actor is None:
        await _safe_answer(message, _NO_USER)
        return
    telegram_id, username, display = actor
    try:
        user, _ = await UserService(session).get_or_register(
            telegram_id=telegram_id, username=username, display_name=display
        )
        game_service = GameSessionService(session)
        async with store.lock_for(user.id):
            active = store.get(user.id)
            if active is None:
                await _safe_answer(message, _NO_ACTIVE_GAME)
                return
            try:
                await game_service.abandon_session(session_id=active.session_id)
            except (NotFoundError, ConflictError):
                pass
            store.remove(user.id)
    except Exception:
        log.error("cmd_cancel failed", exc_info=True)
        await _safe_answer(message, _FRIENDLY_FAILURE)
        return
    await _safe_answer(
        message,
        "Game cancelled. It wasn't recorded and no XP was awarded. "
        "Send /play to try again!",
    )


@router.message(F.text)
async def on_guess(message: Message, session: AsyncSession) -> None:
    """Route plain-text messages to the sender's active game, if any."""
    text = message.text or ""
    if text.startswith("/"):
        return
    actor = _actor(message)
    if actor is None:
        await _safe_answer(message, _NO_USER)
        return
    telegram_id, username, display = actor
    try:
        user, _ = await UserService(session).get_or_register(
            telegram_id=telegram_id, username=username, display_name=display
        )
        async with store.lock_for(user.id):
            active = store.get(user.id)
            if active is None:
                await _safe_answer(message, _NO_ACTIVE_GAME)
                return
            if active.game.finished:
                store.remove(user.id)
                await _safe_answer(
                    message, "That game already ended. Send /play for a new one!"
                )
                return
            try:
                value = guessing.parse_guess(text, active.game.config)
            except guessing.InvalidGuessError as exc:
                await _safe_answer(message, str(exc))
                return
            outcome = active.game.evaluate(value)
            if outcome in guessing.TERMINAL:
                await _finish_guessing_game(message, session, user.id, active, value, outcome)
            else:
                active.game.register(value)
                hint = "Too high" if outcome == guessing.TOO_HIGH else "Too low"
                await _safe_answer(
                    message,
                    f"{hint}! {active.game.attempts_left} guess(es) left.",
                )
    except Exception:
        log.error("on_guess failed", exc_info=True)
        await _safe_answer(message, _FRIENDLY_FAILURE)


async def _finish_guessing_game(
    message: Message,
    session: AsyncSession,
    user_id,
    active: ActiveGame,
    value: int,
    outcome: str,
) -> None:
    """Persist a terminal guess. Memory mutates only after a successful save,
    so a failed save never consumes the guess: the player can simply resend."""
    game = active.game
    won = outcome == guessing.WON
    attempts_used = len(game.guesses) + 1
    xp = guessing.xp_for_result(
        won=won, attempts_used=attempts_used, config=game.config
    )
    metadata = {
        "game": GAME_TYPE_NUMBER_GUESSING,
        "secret": game.secret,
        "guesses": [*game.guesses, value],
        "attempts": attempts_used,
        "range": [game.config.min_value, game.config.max_value],
    }
    game_service = GameSessionService(session)
    try:
        await game_service.finish_session(
            session_id=active.session_id,
            outcome="win" if won else "loss",
            score=attempts_used,
            xp_earned=xp,
            metadata=metadata,
        )
    except ConflictError:
        store.remove(user_id)
        await _safe_answer(
            message, "That game was already recorded. Send /play for a new one!"
        )
        return
    except Exception:
        log.error("persisting finished game failed", exc_info=True)
        await _safe_answer(
            message,
            "I couldn't save that result. Please send your guess again.",
        )
        return
    game.register(value)
    store.remove(user_id)
    if won:
        await _safe_answer(
            message,
            f"You got it in {attempts_used} guess(es)! +{xp} XP. "
            f"Send /play for another round!",
        )
    else:
        await _safe_answer(
            message,
            f"Out of guesses! The number was {game.secret}. +{xp} XP for playing. "
            f"Send /play to try again!",
        )


@router.message(Command("leaderboard"))
async def cmd_leaderboard(message: Message) -> None:
    await _safe_answer(message, LEADERBOARD_TEXT)


@router.message(Command("daily"))
async def cmd_daily(message: Message) -> None:
    await _safe_answer(message, DAILY_TEXT)
