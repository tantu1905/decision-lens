"""players table: create, read, read_all, update, delete."""
from sqlalchemy import delete as sql_delete
from sqlalchemy import select

from src.db.database import Session
from src.db.models import Player

COLS = [c.name for c in Player.__table__.columns if c.name not in ("id", "match_id")]


def as_dict(row: Player) -> dict:
    return {k: getattr(row, k) for k in COLS}


def create(match_id: str, rows: list[dict]) -> int:
    with Session() as session:
        session.add_all([Player(match_id=match_id, **{k: v for k, v in r.items() if k in COLS}) for r in rows])
        session.commit()
    return len(rows)


def read(match_id: str, player_id: str) -> dict | None:
    with Session() as session:
        row = session.scalars(select(Player).where(Player.match_id == match_id, Player.player_id == player_id)).first()
        return as_dict(row) if row else None


def read_all(match_id: str) -> list[dict]:
    with Session() as session:
        q = select(Player).where(Player.match_id == match_id)
        return [as_dict(row) for row in session.scalars(q)]


def update(match_id: str, player_id: str, **fields) -> None:
    with Session() as session:
        row = session.scalars(select(Player).where(Player.match_id == match_id, Player.player_id == player_id)).first()
        for k, v in fields.items():
            setattr(row, k, v)
        session.commit()


def delete(match_id: str) -> None:
    with Session() as session:
        session.execute(sql_delete(Player).where(Player.match_id == match_id))
        session.commit()
