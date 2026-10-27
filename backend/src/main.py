"""Decision Lens v2: FastAPI app, the API at /api/v1 and the screen at /."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from src.api.routes import router as api_router
from src.core.observability import setup_observability, shutdown_observability
from src.core.settings import settings
from src.core.telemetry import (
    CORRELATION_ID_HEADER,
    emit_telemetry_event,
    emit_telemetry_exception,
    ensure_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from src.core.utils import BadInput, NotFound
from src.db.crud import match as crud_match
from src.db.database import create_tables
from src.logic.match import load_sample
from src.services.azure_blob_service import matchFilesBlob
from src.services.azure_foundry_service import foundry

setup_observability(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    if settings.load_sample_on_start and crud_match.read("SYN-0135") is None:
        load_sample()
    try:
        yield
    finally:
        await foundry.close()
        shutdown_observability()


app = FastAPI(title="Decision Lens", version="2.0", lifespan=lifespan)
app.include_router(api_router)


@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    """Every request carries a correlation id (X-Correlation-Id, made here if the caller sent none) that every
    log line and span of the request shows."""
    correlation_id = ensure_correlation_id(request.headers.get(CORRELATION_ID_HEADER))
    request.state.correlation_id = correlation_id
    token = set_correlation_id(correlation_id)
    span = trace.get_current_span()
    if span.is_recording():
        span.set_attribute("workflow.correlation_id", correlation_id)
        span.set_attribute("http.request.method", request.method)
        span.set_attribute("http.route", request.url.path)
    emit_telemetry_event("workflow.request.received", method=request.method, path=request.url.path)
    try:
        response = await call_next(request)
    finally:
        reset_correlation_id(token)
    response.headers[CORRELATION_ID_HEADER] = correlation_id
    if not request.url.path.startswith("/api/"):     # the screen's files: the browser checks for a new version each time
        response.headers["Cache-Control"] = "no-cache"
    if span.is_recording():
        span.set_attribute("http.response.status_code", response.status_code)
        if response.status_code >= 500:
            span.set_status(Status(StatusCode.ERROR))
    return response


def problem(request: Request, status_code: int, err: Exception) -> JSONResponse:
    correlation_id = ensure_correlation_id(getattr(request.state, "correlation_id", None))
    return JSONResponse({"detail": str(err), "correlationId": correlation_id}, status_code=status_code,
                        headers={CORRELATION_ID_HEADER: correlation_id})


@app.exception_handler(NotFound)
async def not_found(request: Request, err: NotFound):
    return problem(request, 404, err)


@app.exception_handler(BadInput)
async def bad_input(request: Request, err: BadInput):
    return problem(request, 400, err)


@app.exception_handler(Exception)
async def unhandled(request: Request, err: Exception):
    emit_telemetry_exception("workflow.request.failed", err, method=request.method, path=request.url.path)
    return problem(request, 500, err)


@app.get("/health")
def health():
    return {"ok": True, "foundry": foundry.ready, "decision1": foundry.decision1_ready, "storage": matchFilesBlob.source}


app.mount("/models", StaticFiles(directory=str(Path(settings.frontend_dir).parent / "models"), check_dir=False), name="models")
app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True, check_dir=False), name="screen")
