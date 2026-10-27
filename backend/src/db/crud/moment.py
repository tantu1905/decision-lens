"""moments table (critical moments and what the agents said about them): create, read, read_all, update, delete."""
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select

from src.db.database import Session
from src.db.models import Moment

COLS = [c.name for c in Moment.__table__.columns if c.name not in ("id", "match_id")]


def as_dict(row: Moment) -> dict:
    return {k: getattr(row, k) for k in COLS}


def create(match_id: str, rows: list[dict]) -> int:
    with Session() as session:
        session.add_all([Moment(match_id=match_id, **r) for r in rows])
        session.commit()
    return len(rows)


def read(match_id: str, event_id: str) -> dict | None:
    with Session() as session:
        row = session.scalars(select(Moment).where(Moment.match_id == match_id, Moment.event_id == event_id)).first()
        return as_dict(row) if row else None


def read_all(match_id: str) -> list[dict]:
    with Session() as session:
        q = select(Moment).where(Moment.match_id == match_id).order_by(Moment.rank)
        return [as_dict(row) for row in session.scalars(q)]


def count(match_id: str) -> int:
    with Session() as session:
        return session.scalar(select(func.count()).where(Moment.match_id == match_id))


def update(match_id: str, event_id: str, **fields) -> None:
    with Session() as session:
        row = session.scalars(select(Moment).where(Moment.match_id == match_id, Moment.event_id == event_id)).first()
        for k, v in fields.items():
            setattr(row, k, v)
        session.commit()


def delete(match_id: str) -> None:
    with Session() as session:
        session.execute(sql_delete(Moment).where(Moment.match_id == match_id))
        session.commit()
