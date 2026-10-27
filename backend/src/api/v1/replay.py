"""Positions frame by frame for the replay on the screen."""
from fastapi import APIRouter, Query

from src.logic import match

router = APIRouter(prefix="/matches/{match_id}", tags=["replay"])


@router.get("/replay")
def get_replay(match_id: str, from_ms: int | None = Query(None), to_ms: int | None = Query(None),
               event_id: str | None = Query(None)):
    return match.frames(match_id, from_ms, to_ms, event_id)
