"""Player report cards, the decisions behind each goal, the fan feed and the rhythm of the match."""
from fastapi import APIRouter, Response

from src.logic import flow
from src.schemas.views import FanFeedView, GoalView, PlayerCard, RhythmView

router = APIRouter(prefix="/matches/{match_id}", tags=["report"])


@router.get("/report", response_model=list[PlayerCard])
def get_report(match_id: str):
    return flow.cards(match_id)


@router.get("/goals", response_model=list[GoalView])
def get_goals(match_id: str):
    return flow.goals(match_id)


@router.get("/rhythm", response_model=RhythmView)
def get_rhythm(match_id: str):
    return flow.rhythm(match_id)


@router.get("/decisions/{event_id}/image", response_class=Response)
def get_decision_image(match_id: str, event_id: str):
    return Response(flow.decision_image(match_id, event_id), media_type="image/png")


@router.get("/fan-feed", response_model=FanFeedView)
def get_fan_feed(match_id: str):
    return flow.read_fan_feed(match_id)
