"""HTTP API: thin routes over the service layer. No game math here."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from brainrush.api.deps import SessionDep, get_verified_identity
from brainrush.services.miniapp import (
    CATALOG,
    DIFFICULTIES,
    PLAYABLE_GAME_TYPES,
    MiniappGameService,
)
from brainrush.game import color_sequence as color_game
from brainrush.game import number_guessing as guessing

router = APIRouter(prefix="/api")


class StartRequest(BaseModel):
    game_type: str = "number_guessing"
    difficulty: str = "hard"


class GuessRequest(BaseModel):
    value: int
    client_guess_id: str = Field(min_length=1, max_length=64)


class MoveRequest(BaseModel):
    color: int = Field(ge=0, le=3)
    client_move_id: str = Field(min_length=1, max_length=64)


IdentityDep = Annotated[dict, Depends(get_verified_identity)]


def _service(session) -> MiniappGameService:
    return MiniappGameService(session)


@router.get("/me")
async def dashboard(identity: IdentityDep, session: SessionDep) -> dict:
    return await _service(session).dashboard(user_id=identity["user_id"])


@router.get("/games")
async def games() -> dict:
    catalog = []
    for entry in CATALOG:
        item = dict(entry)
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
        game_type=body.game_type,
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


@router.get("/history")
async def history(
    identity: IdentityDep,
    session: SessionDep,
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
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    return await _service(session).leaderboard(
        limit=limit, offset=offset, user_id=identity["user_id"]
    )
