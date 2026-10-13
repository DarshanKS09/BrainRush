"""Pure Number Guessing rules + active-game store. No Telegram, no DB."""
import asyncio
import uuid

import pytest

from brainrush.game import number_guessing as ng
from brainrush.game.store import ActiveGame, ActiveGameStore


class _Rng:
    def __init__(self, value):
        self.value = value

    def randint(self, a, b):
        assert a <= self.value <= b
        return self.value


def test_roll_secret_uses_range():
    assert ng.roll_secret(rng=_Rng(1)) == 1
    assert ng.roll_secret(rng=_Rng(100)) == 100


def test_parse_accepts_padded_int():
    assert ng.parse_guess("  42 ") == 42


@pytest.mark.parametrize("bad", [None, "", "   ", "abc", "4.5", "1e2", "101", "0", "-3"])
def test_parse_rejects_without_consuming(bad):
    game = ng.NumberGuessingGame(secret=50)
    with pytest.raises(ng.InvalidGuessError):
        ng.parse_guess(bad)
    assert game.attempts_used == 0 and game.attempts_left == 7


def test_evaluate_does_not_mutate():
    game = ng.NumberGuessingGame(secret=50)
    assert game.evaluate(60) == ng.TOO_HIGH
    assert game.evaluate(40) == ng.TOO_LOW
    assert game.attempts_used == 0


def test_win_and_loss_paths():
    game = ng.NumberGuessingGame(secret=50)
    assert game.register(60) == ng.TOO_HIGH
    assert game.attempts_left == 6
    assert game.register(50) == ng.WON
    assert game.finished

    loser = ng.NumberGuessingGame(secret=50)
    for guess in (1, 2, 3, 4, 5, 6):
        assert loser.register(guess) == ng.TOO_LOW
    assert loser.register(7) == ng.LOST
    assert loser.finished and loser.attempts_used == 7


def test_finished_game_rejects_more_guesses():
    game = ng.NumberGuessingGame(secret=50)
    game.register(50)
    with pytest.raises(ng.GameFinishedError):
        game.evaluate(50)
    with pytest.raises(ng.GameFinishedError):
        game.register(50)


def test_xp_rule_documented_values():
    assert ng.xp_for_result(won=True, attempts_used=1) == 70
    assert ng.xp_for_result(won=True, attempts_used=7) == 10
    assert ng.xp_for_result(won=False, attempts_used=7) == 5


def test_xp_rule_custom_config():
    cfg = ng.NumberGuessingConfig(max_attempts=5, xp_per_spare_attempt=3, loss_xp=1)
    assert ng.xp_for_result(won=True, attempts_used=2, config=cfg) == 12
    assert ng.xp_for_result(won=False, attempts_used=5, config=cfg) == 1


def test_store_isolates_users():
    store = ActiveGameStore()
    a, b = uuid.uuid4(), uuid.uuid4()
    store.put(ActiveGame(user_id=a, session_id=uuid.uuid4(), game_type="g",
                         game=ng.NumberGuessingGame(secret=1)))
    assert store.get(b) is None
    assert store.get(a).game.secret == 1
    assert len(store) == 1
    assert store.remove(a).game.secret == 1
    assert store.remove(a) is None
    assert len(store) == 0


def test_store_locks_are_per_user():
    async def main():
        store = ActiveGameStore()
        a, b = uuid.uuid4(), uuid.uuid4()
        assert store.lock_for(a) is store.lock_for(a)
        assert store.lock_for(a) is not store.lock_for(b)

    asyncio.run(main())
