"""Getting a match ready, and playing it back: the file (AzureBlobService) -> positions in 2D, events, players (PitchService) ->
scored decisions (ScoringService) -> the database. Runs in the background; the match row shows how far it got."""
import io
import json
import random
from functools import lru_cache
from pathlib import Path

import pandas as pd
from fastapi import BackgroundTasks

from src.core.settings import settings
from src.core.telemetry import emit_telemetry_event, emit_telemetry_exception
from src.core.utils import (
    CLIP_AFTER_MS,
    CLIP_BEFORE_MS,
    METRICA_CLIP_MINUTES,
    SAMPLE_MATCH_BLOB,
    made_up_teams,
    name_metrica_players,
    FRAME_COLS,
    BadInput,
    NotFound,
    match_score,
    positions_file,
)
from src.db.crud import event, match, moment, player
from src.schemas.agents import MatchSummary
from src.schemas.views import MatchMeta, MatchView
from src.services.azure_blob_service import matchFilesBlob
from src.services.pitch_service import pitch
from src.services.scoring_service import scoring



# ---------- starting ----------
def upload_metrica(home_csv: bytes, away_csv: bytes, meta: MatchMeta,
                   tasks: BackgroundTasks) -> MatchView:
    """Two raw tracking files in Metrica's format -> a random METRICA_CLIP_MINUTES piece of one half, in our format
    -> queued. Players not named in meta get made-up names (the files have shirt numbers only). Every clip is its own match: its id gets the half, the start minute and a short
    random tail, so a new load never replaces an earlier one."""
    period = random.choice((1, 2))
    start_minute = 45 * (period - 1) + random.randint(0, 45 - METRICA_CLIP_MINUTES)
    match_id = f"{meta.match_id}-H{period}-{start_minute:02d}-{random.randrange(16 ** 4):04x}"
    meta = meta.model_copy(update={"match_id": match_id, "period": period, "start_minute": start_minute})
    t = pitch.read_metrica(home_csv, away_csv, meta.home_id, meta.away_id, period, start_minute, METRICA_CLIP_MINUTES)
    if not meta.players:
        roles = pitch.positions(t, meta.home_id, pitch.keepers(t, meta.home_id, set()))
        meta = meta.model_copy(update={"players": name_metrica_players(t, roles, meta.home_id)})
    buf = io.BytesIO()
    t.to_csv(buf, index=False, compression="gzip")
    name = matchFilesBlob.upload_blob(buf.getvalue(), f"matches/{meta.match_id}/upload.csv.gz")
    start(meta, name)
    tasks.add_task(prepare, meta.match_id, "tracking")
    return view(meta.match_id)


def load_metrica(tasks: BackgroundTasks) -> MatchView:
    """The sample match in the Blob (sample_match/, its two raw Metrica files), a random piece; the teams and players
    get made-up names on every load (the files have shirt numbers only)."""
    home_end, away_end = "_RawTrackingData_Home_Team.csv", "_RawTrackingData_Away_Team.csv"
    homes = sorted(b["name"] for b in matchFilesBlob.list_blobs(SAMPLE_MATCH_BLOB) if b["name"].endswith(home_end))
    if not homes:
        raise BadInput(f"no sample match: put its two RawTrackingData files in the Blob under {SAMPLE_MATCH_BLOB}")
    prefix = homes[0].removeprefix(SAMPLE_MATCH_BLOB).removesuffix(home_end)
    home_name, away_name = made_up_teams()
    meta = MatchMeta(match_id=prefix, home_id="HOM", away_id="AWY", home_name=home_name, away_name=away_name,
                     synthetic=prefix.startswith("SYN-"))
    return upload_metrica(matchFilesBlob.get_blob(homes[0]), matchFilesBlob.get_blob(SAMPLE_MATCH_BLOB + prefix + away_end),
                          meta, tasks)


def load_sample(tasks: BackgroundTasks | None = None) -> MatchView:
    """The synthetic sample match: 15 minutes of SYN-0135 with its players."""
    folder = Path(settings.sample_match_dir)
    raw = json.loads((folder / "match_meta.json").read_text(encoding="utf-8"))
    clip = json.loads((folder / "clip.json").read_text(encoding="utf-8"))
    home, away = (next(t for t in raw["teams"] if t["side"] == s) for s in ("home", "away"))
    meta = MatchMeta(match_id=raw["match_id"], home_id=home["team_id"], away_id=away["team_id"],
                     home_name=home["name"], away_name=away["name"], period=clip["period"],
                     start_minute=clip["start_minute"], score_home=clip["score_home"], score_away=clip["score_away"],
                     synthetic=True, keepers=[p["player_id"] for p in raw["players"] if p["position"] == "GK"],
                     players=raw["players"])
    name = matchFilesBlob.upload_blob((folder / "tracking.csv.gz").read_bytes(), f"matches/{meta.match_id}/upload.csv.gz")
    start(meta, name)
    if tasks is None:
        prepare(meta.match_id, "tracking")
    else:
        tasks.add_task(prepare, meta.match_id, "tracking")
    return view(meta.match_id)


def start(meta: MatchMeta, file_name: str) -> None:
    for table in (moment, event, player, match):     # an earlier match with the same id goes first
        table.delete(meta.match_id)
    match.create(match_id=meta.match_id, home_id=meta.home_id, away_id=meta.away_id, home_name=meta.home_name,
                 away_name=meta.away_name, synthetic=meta.synthetic, meta=meta.model_dump(), tracking_file=file_name,
                 status="loading", step="queued", progress=0.0)


# ---------- the work ----------
def prepare(match_id: str, source: str) -> None:
    """Background job; a failure is written on the match row."""
    try:
        m = match.read(match_id)
        meta = MatchMeta.model_validate(m.meta)
        step(match_id, "2d", 0.1)
        tracking = pitch.read_tracking(matchFilesBlob.get_blob(m.tracking_file), meta.home_id, meta.away_id)
        buf = io.BytesIO()
        tracking.to_csv(buf, index=False, compression="gzip")
        matchFilesBlob.upload_blob(buf.getvalue(), positions_file(match_id))
        step(match_id, "events", 0.6)
        keepers = pitch.keepers(tracking, meta.home_id, set(meta.keepers))
        events, frames = pitch.events(tracking, meta.home_id, keepers, meta.period, meta.start_minute)
        names = {meta.home_id: meta.home_name, meta.away_id: meta.away_name}
        players = pitch.players(tracking, names, keepers, meta.home_id, meta.players)
        for p in players:
            if p["player_id"] in keepers:
                p["position"] = "GK"
        step(match_id, "scoring", 0.75)
        events = scoring.score_state(events, meta.home_id)
        events[["score_home", "score_away"]] += [meta.score_home, meta.score_away]
        scored = scoring.score(events, frames, {p["player_id"]: p for p in players}, meta.home_id)
        name = {p["player_id"]: p["name"] for p in players}
        role = {p["player_id"]: p.get("position") for p in players}
        by_event = {k: g[[c for c in FRAME_COLS if c in g]].to_dict("records") for k, g in frames.groupby("event_id")}
        rows = []
        for r in scored.to_dict("records"):
            r["frame"] = [{**f, "name": name.get(f["player_id"]), "position": role.get(f["player_id"])}
                          for f in by_event.get(r["event_id"], [])]
            r["options"] = r.get("options") if isinstance(r.get("options"), list) else None
            rows.append(r)
        player.create(match_id, players)
        event.create(match_id, rows)
        n = sum(1 for r in rows if r["options"])
        stats = {"distance_m": pitch.distances(tracking), "shot_speed": pitch.shot_speeds(tracking, events)}
        match.update(match_id, status="ready", step="ready", progress=1.0, meta=m.meta | {"stats": stats},
                     message=f"{len(rows)} events, {n} decisions scored")
        emit_telemetry_event("match.ready", match_id=match_id, events=len(rows), decisions=n, source=source)
    except Exception as err:                    # noqa: BLE001  (any failure ends the job with its reason)
        emit_telemetry_exception("match.prepare_failed", err, match_id=match_id)
        match.update(match_id, status="failed", step=None, message=str(err)[:500] or type(err).__name__)


def step(match_id: str, name: str, progress: float) -> None:
    match.update(match_id, step=name, progress=progress)


# ---------- reading ----------
def view(match_id: str) -> MatchView:
    m = match.read(match_id)
    if m is None:
        raise NotFound(f"no match {match_id}")
    score = match_score(m.meta, m.home_id, event.goal_teams(match_id))
    return MatchView(match_id=m.match_id, home_id=m.home_id, away_id=m.away_id, home_name=m.home_name,
                     away_name=m.away_name, status=m.status, step=m.step, progress=m.progress, message=m.message,
                     decisions=event.decisions(match_id), moments=moment.count(match_id),
                     score=score, summary=MatchSummary.model_validate(m.summary) if m.summary else None, created_at=m.created_at)


def all_matches() -> list[MatchView]:
    return [view(m.match_id) for m in match.read_all()]


def must_be_ready(match_id: str):
    m = match.read(match_id)
    if m is None:
        raise NotFound(f"no match {match_id}")
    if m.status not in ("ready", "running", "done"):
        raise BadInput(f"match {match_id} is {m.status}, not ready yet")
    return m


def positions(match_id: str) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(matchFilesBlob.get_blob(positions_file(match_id))), compression="gzip", dtype={"team_id": "string"},
                       low_memory=False)


# ---------- replay ----------
@lru_cache(maxsize=4)
def _positions(match_id: str, loaded_at: str):
    """Kept in memory per match; a match loaded again (new loaded_at) is read afresh."""
    return positions(match_id)


def frames(match_id: str, from_ms: int | None = None, to_ms: int | None = None,
           event_id: str | None = None) -> list[dict]:
    """Positions between two times, or around one event (8 s before to 3 s after)."""
    m = must_be_ready(match_id)
    if event_id:
        e = event.read(match_id, event_id)
        if e is None:
            raise NotFound(f"no event {event_id}")
        from_ms, to_ms = e["ts_ms"] - CLIP_BEFORE_MS, e["ts_ms"] + CLIP_AFTER_MS
    t = _positions(match_id, m.created_at.isoformat())
    lo = int(t.ts_ms.min()) if from_ms is None else from_ms
    squad = {p["player_id"]: p for p in player.read_all(match_id)}
    out = pitch.frames(t, lo, lo + 60_000 if to_ms is None else to_ms)
    for f in out:                                  # the replay shows the same numbers as the picture, and the keepers
        for o in f["objects"]:
            o["shirt"] = squad.get(o["id"], {}).get("shirt")
            o["position"] = squad.get(o["id"], {}).get("position")
    return out
