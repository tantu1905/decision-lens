"""Every route of the API under one router; main.py includes only this one."""
from fastapi import APIRouter

from src.api.v1.flow import router as flow_router
from src.api.v1.match import router as match_router
from src.api.v1.replay import router as replay_router
from src.api.v1.report import router as report_router

router = APIRouter(prefix="/api/v1")
for r in (match_router, flow_router, replay_router, report_router):
    router.include_router(r)
