"""The critical-moment flow: start it, read the moments and their pictures."""
from fastapi import APIRouter, BackgroundTasks, Response

from src.logic import flow
from src.schemas.views import FlowStarted, MomentView

router = APIRouter(prefix="/matches/{match_id}", tags=["flow"])


@router.post("/flow", response_model=FlowStarted)
def start_flow(match_id: str, tasks: BackgroundTasks):
    return flow.start(match_id, tasks)


@router.get("/moments", response_model=list[MomentView])
def list_moments(match_id: str):
    return flow.moments(match_id)


@router.get("/moments/{event_id}", response_model=MomentView)
def get_moment(match_id: str, event_id: str):
    return flow.one_moment(match_id, event_id)


@router.get("/moments/{event_id}/image", response_class=Response)
def get_moment_image(match_id: str, event_id: str):
    return Response(flow.moment_image(match_id, event_id), media_type="image/png")
