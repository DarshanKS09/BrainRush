"""HTTP API: thin routes over the service layer. No game math here."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from brainrush.api.deps import (
    ExpensiveLimitDep,
    InviteLimitDep,
    RoomLimitDep,
    SessionDep,
    get_verified_identity,
    get_verified_telegram_identity,
)
from brainrush.config import Settings
from brainrush.services.friends import FriendService
from brainrush.services.matches import MatchService
from brainrush.services.referrals import ReferralService
from brainrush.services.miniapp import (
    CATALOG,
    DIFFICULTIES,
    PLAYABLE_GAME_TYPES,
    MiniappGameService,
)
from brainrush.game import color_sequence as color_game
from brainrush.game import maze_race as maze_race
from brainrush.game import number_guessing as guessing
from brainrush.game import perfect_second as perfect_game
from brainrush.game import reflex_rush as reflex_game

router = APIRouter(prefix="/api")


class StartRequest(BaseModel):
    game_type: str = "number_guessing"
    difficulty: str = "hard"
    match_id: uuid.UUID | None = None


class GuessRequest(BaseModel):
    value: int
    client_guess_id: str = Field(min_length=1, max_length=64)


class MoveRequest(BaseModel):
    color: int = Field(ge=0, le=3)
    client_move_id: str = Field(min_length=1, max_length=64)


class DirectionRequest(BaseModel):
    direction: str = Field(min_length=1, max_length=10)
    client_move_id: str = Field(min_length=1, max_length=64)


class ReflexRound(BaseModel):
    reaction_ms: int | None = Field(default=None, ge=1, le=10000)
    false_start: bool = False


class ReflexFinishRequest(BaseModel):
    rounds: list[ReflexRound] = Field(min_length=5, max_length=5)
    client_submission_id: str = Field(min_length=1, max_length=64)


class PerfectStopRequest(BaseModel):
    actual_ms: float
    client_submission_id: str = Field(min_length=1, max_length=64)


IdentityDep = Annotated[dict, Depends(get_verified_identity)]
TelegramIdentityDep = Annotated[dict, Depends(get_verified_telegram_identity)]


def _referrals(session, settings: Settings) -> ReferralService:
    return ReferralService(
        session,
        referrer_xp=settings.REFERRER_XP,
        referred_xp=settings.REFERRED_XP,
    )


def _service(session) -> MiniappGameService:
    return MiniappGameService(session)


def _matches(session, settings: Settings) -> MatchService:
    return MatchService(
        session,
        completion_xp=settings.MATCH_COMPLETION_XP,
        win_bonus=settings.MATCH_WIN_BONUS,
        daily_cap=settings.MATCH_DAILY_XP_CAP,
        lobby_ttl_hours=settings.MATCH_LOBBY_TTL_HOURS,
        invite_ttl_days=settings.MATCH_INVITE_TTL_DAYS,
        default_minutes=settings.MATCH_DEFAULT_MINUTES,
    )


@router.get("/me")
async def dashboard(identity: IdentityDep, session: SessionDep) -> dict:
    return await _service(session).dashboard(user_id=identity["user_id"])


@router.get("/games")
async def games() -> dict:
    from brainrush.game import multiplayer as mp_game

    catalog = []
    for entry in CATALOG:
        item = dict(entry)
        try:
            spec = mp_game.spec_for(entry["id"])
            item["multiplayer"] = {"modes": sorted(spec.modes)}
        except ValueError:
            item["multiplayer"] = None
        if entry["id"] == "number_guessing":
            item["xp_rules"] = {
                did: {
                    "win_first_try": guessing.xp_for_result(
                        won=True, attempts_used=1, config=cfg
                    ),
                    "win_last_try": guessing.xp_for_result(
                        won=True, attempts_used=cfg.max_attempts, config=cfg
                    ),
                    "loss": guessing.xp_for_result(
                        won=False, attempts_used=cfg.max_attempts, config=cfg
                    ),
                }
                for did, cfg in DIFFICULTIES.items()
            }
        elif entry["id"] == "color_sequence":
            item["xp_rules"] = {
                did: {
                    "win": color_game.xp_for_color_result(
                        levels_completed=cfg.max_level, won=True, config=cfg
                    ),
                    "loss_per_level": cfg.xp_per_level,
                }
                for did, cfg in color_game.COLOR_DIFFICULTIES.items()
            }
        elif entry["id"] == "perfect_second":
            item["xp_rules"] = {
                did: {
                    "perfect": 100,
                    "win_accuracy": 90,
                    "win_error_percent": perfect_game.WIN_ERROR_PERCENT,
                    "target_min_ms": cfg.min_target_ms,
                    "target_max_ms": cfg.max_target_ms,
                    "target_step_ms": cfg.step_ms,
                }
                for did, cfg in perfect_game.PERFECT_DIFFICULTIES.items()
            }
        elif entry["id"] == "reflex_rush":
            item["xp_rules"] = {
                did: {
                    "win_bonus": cfg.win_bonus,
                    "xp_perfect": cfg.xp_perfect,
                    "xp_good": cfg.xp_good,
                    "xp_slow": cfg.xp_slow,
                    "win_avg_ms": cfg.win_avg_ms,
                    "wait_min_ms": cfg.wait_min_ms,
                    "wait_max_ms": cfg.wait_max_ms,
                }
                for did, cfg in reflex_game.REFLEX_DIFFICULTIES.items()
            }
        elif entry["id"] == "maze_race":
            item["xp_rules"] = {
                did: {
                    "base_xp": cfg.base_xp,
                    "time_bonus_xp": cfg.time_bonus_xp,
                    "path_bonus_xp": cfg.path_bonus_xp,
                    "par_time_s": cfg.par_time_s,
                    "rows": cfg.rows,
                    "cols": cfg.cols,
                    "branching": cfg.branching,
                }
                for did, cfg in maze_race.MAZE_DIFFICULTIES.items()
            }
        catalog.append(item)
    return {"games": catalog}


@router.post("/sessions")
async def start_session(
    body: StartRequest, identity: IdentityDep, session: SessionDep
) -> dict:
    if body.game_type not in PLAYABLE_GAME_TYPES:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="game is not playable yet")
    return await _service(session).start_game(
        user_id=identity["user_id"], difficulty=body.difficulty,
        game_type=body.game_type, match_id=body.match_id,
    )


@router.get("/sessions/{session_id}")
async def get_state(
    session_id: uuid.UUID, identity: IdentityDep, session: SessionDep
) -> dict:
    return await _service(session).get_state(
        session_id=session_id, user_id=identity["user_id"]
    )


@router.post("/sessions/{session_id}/guess")
async def guess(
    session_id: uuid.UUID,
    body: GuessRequest,
    identity: IdentityDep,
    session: SessionDep,
) -> dict:
    return await _service(session).guess(
        session_id=session_id,
        user_id=identity["user_id"],
        value=body.value,
        client_guess_id=body.client_guess_id,
    )


@router.delete("/sessions/{session_id}")
async def cancel(
    session_id: uuid.UUID, identity: IdentityDep, session: SessionDep
) -> dict:
    return await _service(session).cancel(
        session_id=session_id, user_id=identity["user_id"]
    )


@router.post("/sessions/{session_id}/move")
async def move(
    session_id: uuid.UUID,
    body: MoveRequest,
    identity: IdentityDep,
    session: SessionDep,
) -> dict:
    return await _service(session).tap(
        session_id=session_id,
        user_id=identity["user_id"],
        color=body.color,
        client_move_id=body.client_move_id,
    )


@router.post("/sessions/{session_id}/direction")
async def direction(
    session_id: uuid.UUID,
    body: DirectionRequest,
    identity: IdentityDep,
    session: SessionDep,
) -> dict:
    return await _service(session).direction(
        session_id=session_id,
        user_id=identity["user_id"],
        direction=body.direction,
        client_move_id=body.client_move_id,
    )


@router.post("/sessions/{session_id}/finish")
async def finish_reflex(
    session_id: uuid.UUID,
    body: ReflexFinishRequest,
    identity: IdentityDep,
    session: SessionDep,
) -> dict:
    return await _service(session).finish_reflex(
        session_id=session_id,
        user_id=identity["user_id"],
        rounds=[r.model_dump() for r in body.rounds],
        client_submission_id=body.client_submission_id,
    )


@router.post("/sessions/{session_id}/stop")
async def stop_perfect(
    session_id: uuid.UUID,
    body: PerfectStopRequest,
    identity: IdentityDep,
    session: SessionDep,
) -> dict:
    """Submit the single STOP time for Perfect Second. Error and XP are
    computed server-side from the stored target; the submission carries
    only the measured elapsed time plus an idempotency key."""
    return await _service(session).stop_perfect(
        session_id=session_id,
        user_id=identity["user_id"],
        actual_ms=body.actual_ms,
        client_submission_id=body.client_submission_id,
    )


@router.get("/history")
async def history(
    identity: IdentityDep,
    session: SessionDep,
    _expensive: ExpensiveLimitDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    return {
        "items": await _service(session).history(
            user_id=identity["user_id"], limit=limit, offset=offset
        )
    }


@router.get("/leaderboard")
async def leaderboard(
    identity: IdentityDep,
    session: SessionDep,
    _expensive: ExpensiveLimitDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    return await _service(session).leaderboard(
        limit=limit, offset=offset, user_id=identity["user_id"]
    )


class ClaimRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)


@router.get("/referrals/mine")
async def referral_link(
    request: Request, identity: IdentityDep, session: SessionDep
) -> dict:
    """Stable personal code + deep link (link is null until the bot username
    is configured server-side; the code always works). Named-app format when
    MINIAPP_SHORT_NAME is set, Main-Mini-App format otherwise."""
    settings: Settings = request.app.state.settings
    data = await _referrals(session, settings).build_link(
        user_id=identity["user_id"],
        bot_username=settings.TELEGRAM_BOT_USERNAME,
        app_short_name=settings.MINIAPP_SHORT_NAME,
    )
    return {
        **data,
        "referrer_xp": settings.REFERRER_XP,
        "referred_xp": settings.REFERRED_XP,
    }


@router.post("/referrals/claim")
async def referral_claim(
    body: ClaimRequest,
    request: Request,
    telegram: TelegramIdentityDep,
    session: SessionDep,
) -> dict:
    """Attribute a newcomer via referral code. Uses the verified Telegram
    identity only — never any id from the URL or body. Idempotent: a repeat
    claim by the same newcomer returns the stored credit."""
    settings: Settings = request.app.state.settings
    return await _referrals(session, settings).claim(
        code=body.code,
        telegram_id=telegram["telegram_id"],
        username=telegram["username"],
        display_name=telegram["display_name"],
    )


@router.get("/referrals/stats")
async def referral_stats(
    request: Request, identity: IdentityDep, session: SessionDep
) -> dict:
    settings: Settings = request.app.state.settings
    return await _referrals(session, settings).stats(user_id=identity["user_id"])


class FriendAddRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class MatchCreateRequest(BaseModel):
    game_type: str = "number_guessing"
    mode: str = "duel"
    difficulty: str = "hard"
    max_players: int | None = Field(default=None, ge=2, le=32)


class MatchJoinTokenRequest(BaseModel):
    token: str = Field(min_length=1, max_length=64)


class MatchJoinCodeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=12)


class MatchInviteRequest(BaseModel):
    friend_user_id: uuid.UUID


class MatchSubmitRequest(BaseModel):
    session_id: uuid.UUID


def _friends(session) -> FriendService:
    return FriendService(session)


@router.get("/friends/mine")
async def friend_code(identity: IdentityDep, session: SessionDep) -> dict:
    """Stable personal friend code. Friendships award no XP and never
    interact with referral attribution."""
    return await _friends(session).my_code(user_id=identity["user_id"])


@router.get("/friends")
async def friends_list(identity: IdentityDep, session: SessionDep) -> dict:
    """Symmetric friends list: public display data only, no Telegram ids."""
    return {"friends": await _friends(session).list_friends(user_id=identity["user_id"])}


@router.post("/friends/add")
async def friend_add(
    body: FriendAddRequest, identity: IdentityDep, session: SessionDep
) -> dict:
    """Add a friend by code, immediately. Uses the verified identity only —
    never any id from the body. Idempotent: an existing pair returns
    added=False instead of duplicating."""
    return await _friends(session).add_friend(
        user_id=identity["user_id"], code=body.code
    )


@router.post("/matches")
async def match_create(
    body: MatchCreateRequest, request: Request,
    identity: IdentityDep, session: SessionDep,
    _room: RoomLimitDep,
) -> dict:
    """Create a match lobby as host. The host is seated immediately."""
    settings: Settings = request.app.state.settings
    return await _matches(session, settings).create_match(
        host_user_id=identity["user_id"],
        game_type=body.game_type,
        mode=body.mode,
        difficulty=body.difficulty,
        max_players=body.max_players,
    )


@router.get("/matches/mine")
async def match_mine(
    request: Request,
    identity: IdentityDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """My matches, newest first. Completed matches carry my rank."""
    settings: Settings = request.app.state.settings
    return {
        "items": await _matches(session, settings).my_matches(
            user_id=identity["user_id"], limit=limit, offset=offset
        )
    }


@router.get("/matches/invites")
async def match_invites(
    request: Request, identity: IdentityDep, session: SessionDep
) -> dict:
    """Pending match invitations with lobby summaries. Joinable ones only."""
    settings: Settings = request.app.state.settings
    return {
        "items": await _matches(session, settings).my_invites(
            user_id=identity["user_id"]
        )
    }


@router.get("/matches/{match_id}")
async def match_get(
    match_id: uuid.UUID, request: Request,
    identity: IdentityDep, session: SessionDep,
) -> dict:
    """Lobby / live / completed view. Participants only; lobbies past their
    TTL expire and past-deadline matches finalize on read."""
    settings: Settings = request.app.state.settings
    return await _matches(session, settings).get_match(
        user_id=identity["user_id"], match_id=match_id
    )


@router.post("/matches/join")
async def match_join_by_token(
    body: MatchJoinTokenRequest, request: Request,
    identity: IdentityDep, session: SessionDep,
    _room: RoomLimitDep,
) -> dict:
    """Join via share-link token. Idempotent: repeat joins return the lobby."""
    settings: Settings = request.app.state.settings
    return await _matches(session, settings).join_by_token(
        user_id=identity["user_id"], token=body.token
    )


@router.post("/matches/join-by-code")
async def match_join_by_code(
    body: MatchJoinCodeRequest, request: Request,
    identity: IdentityDep, session: SessionDep,
    _room: RoomLimitDep,
) -> dict:
    """Join via the human-readable room code (manual entry). The code is not
    an authorization secret: identity comes from verified initData.
    Idempotent: repeat joins return the lobby."""
    settings: Settings = request.app.state.settings
    return await _matches(session, settings).join_by_code(
        user_id=identity["user_id"], room_code=body.code
    )


@router.post("/matches/{match_id}/join")
async def match_join(
    match_id: uuid.UUID, request: Request,
    identity: IdentityDep, session: SessionDep,
    _room: RoomLimitDep,
) -> dict:
    """Join a known lobby (e.g. from an in-app invitation). Idempotent."""
    settings: Settings = request.app.state.settings
    return await _matches(session, settings).join_match(
        user_id=identity["user_id"], match_id=match_id
    )


@router.post("/matches/{match_id}/invite")
async def match_invite(
    match_id: uuid.UUID, body: MatchInviteRequest, request: Request,
    identity: IdentityDep, session: SessionDep,
    _invite: InviteLimitDep,
) -> dict:
    """Host invites a friend by user id. Friends only; duplicates return
    the stored invitation instead of erroring."""
    settings: Settings = request.app.state.settings
    return await _matches(session, settings).invite_friend(
        host_user_id=identity["user_id"],
        match_id=match_id,
        friend_user_id=body.friend_user_id,
    )


@router.get("/matches/{match_id}/invite-link")
async def match_invite_link(
    match_id: uuid.UUID, request: Request,
    identity: IdentityDep, session: SessionDep,
) -> dict:
    """Shareable lobby link (participants only). Link is null until the bot
    username is configured server-side; the token always works."""
    settings: Settings = request.app.state.settings
    return await _matches(session, settings).build_match_link(
        match_id=match_id,
        user_id=identity["user_id"],
        bot_username=settings.TELEGRAM_BOT_USERNAME,
        app_short_name=settings.MINIAPP_SHORT_NAME,
    )


@router.post("/matches/{match_id}/start")
async def match_start(
    match_id: uuid.UUID, request: Request,
    identity: IdentityDep, session: SessionDep,
) -> dict:
    """Host starts the match once minimum seats are filled. Synchronized
    server timestamps are the authoritative start/deadline."""
    settings: Settings = request.app.state.settings
    return await _matches(session, settings).start_match(
        host_user_id=identity["user_id"], match_id=match_id
    )


@router.post("/matches/{match_id}/submit")
async def match_submit(
    match_id: uuid.UUID, body: MatchSubmitRequest, request: Request,
    identity: IdentityDep, session: SessionDep,
) -> dict:
    """Attach one finished solo session to the caller's seat. Exactly one
    session per seat; resubmits replay the current view."""
    settings: Settings = request.app.state.settings
    return await _matches(session, settings).submit_result(
        user_id=identity["user_id"],
        match_id=match_id,
        session_id=body.session_id,
    )


@router.post("/matches/{match_id}/finalize")
async def match_finalize(
    match_id: uuid.UUID, request: Request,
    identity: IdentityDep, session: SessionDep,
) -> dict:
    """Settle a stalled match once everyone finished or the deadline passed.
    Idempotent: completed matches return the stored results."""
    settings: Settings = request.app.state.settings
    return await _matches(session, settings).finalize_match(
        user_id=identity["user_id"], match_id=match_id
    )


@router.post("/matches/{match_id}/cancel")
async def match_cancel(
    match_id: uuid.UUID, request: Request,
    identity: IdentityDep, session: SessionDep,
) -> dict:
    """Host cancels a lobby. Active matches end via deadline/completion."""
    settings: Settings = request.app.state.settings
    return await _matches(session, settings).cancel_match(
        host_user_id=identity["user_id"], match_id=match_id
    )


@router.post("/matches/{match_id}/leave")
async def match_leave(
    match_id: uuid.UUID, request: Request,
    identity: IdentityDep, session: SessionDep,
) -> dict:
    """Leave a lobby seat (host transfers to the oldest remaining player,
    or the lobby cancels when empty)."""
    settings: Settings = request.app.state.settings
    return await _matches(session, settings).leave_match(
        user_id=identity["user_id"], match_id=match_id
    )


@router.post("/matches/{match_id}/rematch")
async def match_rematch(
    match_id: uuid.UUID, request: Request,
    identity: IdentityDep, session: SessionDep,
) -> dict:
    """Fresh match with the same settings; prior participants auto-invited.
    Never reopens the old match."""
    settings: Settings = request.app.state.settings
    return await _matches(session, settings).rematch(
        user_id=identity["user_id"], match_id=match_id
    )
