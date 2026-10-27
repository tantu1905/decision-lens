"""The four tables. Positions of a whole match are kept as a file (AzureBlobService), not in SQL."""
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def now():
    return datetime.now(timezone.utc)


class Match(Base):
    __tablename__ = "matches"
    match_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    home_id: Mapped[str] = mapped_column(String(32))
    away_id: Mapped[str] = mapped_column(String(32))
    home_name: Mapped[str] = mapped_column(String(128))
    away_name: Mapped[str] = mapped_column(String(128))
    synthetic: Mapped[bool] = mapped_column(default=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    tracking_file: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="new")   # new, loading, ready, running, done, failed
    step: Mapped[str | None] = mapped_column(String(64), nullable=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Player(Base):
    __tablename__ = "players"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(String(64), index=True)
    player_id: Mapped[str] = mapped_column(String(64))
    team_id: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    position: Mapped[str | None] = mapped_column(String(8), nullable=True)
    shirt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    strength: Mapped[float | None] = mapped_column(Float, nullable=True)
    technique: Mapped[float | None] = mapped_column(Float, nullable=True)
    defending: Mapped[float | None] = mapped_column(Float, nullable=True)


class Event(Base):
    """One on-ball event; decisions also carry their options and scores, and the freeze frame."""
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[str] = mapped_column(String(32))
    period: Mapped[int] = mapped_column(Integer)
    minute: Mapped[int] = mapped_column(Integer)
    second: Mapped[int] = mapped_column(Integer)
    ts_ms: Mapped[int] = mapped_column(Integer)
    team_id: Mapped[str] = mapped_column(String(32))
    player_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    type: Mapped[str] = mapped_column(String(32))
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pass_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    recipient_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    end_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_home: Mapped[int] = mapped_column(Integer, default=0)
    score_away: Mapped[int] = mapped_column(Integer, default=0)
    frame: Mapped[list | None] = mapped_column(JSON, nullable=True)
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)
    chosen_ev: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_ev: Mapped[float | None] = mapped_column(Float, nullable=True)
    safe_best_ev: Mapped[float | None] = mapped_column(Float, nullable=True)
    regret: Mapped[float | None] = mapped_column(Float, nullable=True)
    regret_rel: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    importance: Mapped[float | None] = mapped_column(Float, nullable=True)


class Moment(Base):
    """One critical moment and what the agents said about it."""
    __tablename__ = "moments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[str] = mapped_column(String(32))
    rank: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(1024), default="")
    status: Mapped[str] = mapped_column(String(16), default="waiting")   # waiting, running, done, failed
    image_file: Mapped[str | None] = mapped_column(String(256), nullable=True)
    analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    decision1: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    coach: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="agent")
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
