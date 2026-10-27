"""Matches: list them, load a new piece of the sample match and analyse it, read one."""
from fastapi import APIRouter, BackgroundTasks

from src.logic import flow, match
from src.schemas.views import MatchView

router = APIRouter(prefix="/matches", tags=["matches"])


@router.get("", response_model=list[MatchView])
def list_matches():
    return match.all_matches()


@router.post("/sample/analyse", response_model=MatchView)
def load_and_analyse(tasks: BackgroundTasks):
    return flow.load_and_run(tasks)


@router.get("/{match_id}", response_model=MatchView)
def get_match(match_id: str):
    return match.view(match_id)
