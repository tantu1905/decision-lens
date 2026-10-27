"""matches table: create, read, read_all, update, delete."""
from sqlalchemy import delete as sql_delete
from sqlalchemy import select

from src.db.database import Session
from src.db.models import Match


def create(**fields) -> Match:
    with Session() as session:
        m = Match(**fields)
        session.add(m)
        session.commit()
        return m


def read(match_id: str) -> Match | None:
    with Session() as session:
        return session.get(Match, match_id)


def read_all() -> list[Match]:
    with Session() as session:
        return list(session.scalars(select(Match).order_by(Match.created_at.desc())))


def update(match_id: str, **fields) -> Match:
    with Session() as session:
        m = session.get(Match, match_id)
        for k, v in fields.items():
            setattr(m, k, v)
        session.commit()
        return m


def delete(match_id: str) -> None:
    with Session() as session:
        session.execute(sql_delete(Match).where(Match.match_id == match_id))
        session.commit()
