"""events table (on-ball events with their options, scores and freeze frames): create, read, read_all,
update, delete."""
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select

from src.core.utils import clean
from src.db.database import Session
from src.db.models import Event

COLS = [c.name for c in Event.__table__.columns if c.name not in ("id", "match_id")]


def as_dict(row: Event) -> dict:
    return {k: getattr(row, k) for k in COLS}


def create(match_id: str, rows: list[dict]) -> int:
    with Session() as session:
        session.add_all([Event(match_id=match_id, **{k: clean(r[k]) for k in COLS if k in r}) for r in rows])
        session.commit()
    return len(rows)


def read(match_id: str, event_id: str) -> dict | None:
    with Session() as session:
        row = session.scalars(select(Event).where(Event.match_id == match_id, Event.event_id == event_id)).first()
        return as_dict(row) if row else None


def read_all(match_id: str, event_ids: list[str] | None = None) -> list[dict]:
    """Every event of the match, or only these ones (one query, not one per event)."""
    with Session() as session:
        q = select(Event).where(Event.match_id == match_id).order_by(Event.ts_ms, Event.event_id)
        if event_ids is not None:
            q = q.where(Event.event_id.in_(event_ids))
        return [as_dict(row) for row in session.scalars(q)]


def decisions(match_id: str) -> int:
    """How many events of the match were scored (they have options, so a chosen_ev)."""
    with Session() as session:
        return session.scalar(select(func.count()).where(Event.match_id == match_id, Event.chosen_ev.is_not(None)))


def goal_teams(match_id: str) -> list[str]:
    """The team id of every goal in the match."""
    with Session() as session:
        return list(session.scalars(select(Event.team_id).where(Event.match_id == match_id, Event.outcome == "goal")))


def update(match_id: str, event_id: str, **fields) -> None:
    with Session() as session:
        row = session.scalars(select(Event).where(Event.match_id == match_id, Event.event_id == event_id)).first()
        for k, v in fields.items():
            setattr(row, k, v)
        session.commit()


def delete(match_id: str) -> None:
    with Session() as session:
        session.execute(sql_delete(Event).where(Event.match_id == match_id))
        session.commit()
