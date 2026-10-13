"""Number Guessing: pure game rules (no Telegram, no database).

One game: the bot holds a secret integer in [min_value, max_value]; the player
has max_attempts guesses. A correct guess wins, exhausting all guesses loses.

XP RULE (applied only when a game completes; abandoned games award nothing):
  win  -> (max_attempts - attempts_used + 1) * xp_per_spare_attempt
          e.g. defaults: first-try win = 70 XP, last-try win = 10 XP.
  loss -> loss_xp (default 5, participation).
Score persisted = attempts used (fewer is better).

All knobs live in NumberGuessingConfig so future games/rewards can reuse the
pattern without touching this logic.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

TOO_HIGH = "too_high"
TOO_LOW = "too_low"
WON = "won"
LOST = "lost"
TERMINAL = frozenset({WON, LOST})


class InvalidGuessError(ValueError):
    """User input is not a usable guess (does not consume an attempt)."""


class GameFinishedError(RuntimeError):
    """A guess was submitted to an already finished game."""


@dataclass(frozen=True)
class NumberGuessingConfig:
    min_value: int = 1
    max_value: int = 100
    max_attempts: int = 7
    xp_per_spare_attempt: int = 10
    loss_xp: int = 5


DEFAULT_CONFIG = NumberGuessingConfig()


def roll_secret(config: NumberGuessingConfig = DEFAULT_CONFIG, rng=None) -> int:
    """Draw the secret. `rng` is injectable for deterministic tests."""
    source = rng if rng is not None else random
    return source.randint(config.min_value, config.max_value)


def parse_guess(text: str | None, config: NumberGuessingConfig = DEFAULT_CONFIG) -> int:
    """Parse raw user text. Raises InvalidGuessError (never consumes a guess)."""
    if text is None:
        raise InvalidGuessError("Send a number to guess.")
    cleaned = text.strip()
    try:
        value = int(cleaned)
    except (TypeError, ValueError):
        raise InvalidGuessError(
            f"That wasn't a number. Send a whole number from "
            f"{config.min_value} to {config.max_value}."
        ) from None
    if not config.min_value <= value <= config.max_value:
        raise InvalidGuessError(
            f"Out of range. Guess a whole number from "
            f"{config.min_value} to {config.max_value}."
        )
    return value


def xp_for_result(
    *, won: bool, attempts_used: int, config: NumberGuessingConfig = DEFAULT_CONFIG
) -> int:
    if won:
        return (config.max_attempts - attempts_used + 1) * config.xp_per_spare_attempt
    return config.loss_xp


class NumberGuessingGame:
    """In-memory state for one player's game. Not shared between users."""

    def __init__(
        self, secret: int, config: NumberGuessingConfig = DEFAULT_CONFIG
    ) -> None:
        if not config.min_value <= secret <= config.max_value:
            raise ValueError("secret out of range")
        self.secret = secret
        self.config = config
        self.guesses: list[int] = []
        self.finished = False

    @property
    def attempts_used(self) -> int:
        return len(self.guesses)

    @property
    def attempts_left(self) -> int:
        return max(0, self.config.max_attempts - len(self.guesses))

    def evaluate(self, value: int) -> str:
        """Outcome of a hypothetical guess; does not mutate state."""
        if self.finished:
            raise GameFinishedError("game is already finished")
        if value == self.secret:
            return WON
        if len(self.guesses) + 1 >= self.config.max_attempts:
            return LOST
        return TOO_HIGH if value > self.secret else TOO_LOW

    def register(self, value: int) -> str:
        """Record a guess and return its outcome."""
        outcome = self.evaluate(value)
        self.guesses.append(value)
        if outcome in TERMINAL:
            self.finished = True
        return outcome
