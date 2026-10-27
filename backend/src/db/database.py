"""Engine and the Session every crud file uses. The tables come from models.py (MODEL_METADATA): Alembic
migrations (backend/alembic) make them in a real database, create_tables only in a local SQLite file."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.core.settings import settings
from src.db import models
from src.db.dbUtils import parse_connection_string

MODEL_METADATA = models.Base.metadata
connection_string = parse_connection_string(settings.db_connection_string)
engine_kwargs = {"pool_recycle": 3600, "pool_pre_ping": True}
if connection_string.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
elif connection_string.startswith("mssql"):
    engine_kwargs["fast_executemany"] = True

engine = create_engine(connection_string, **engine_kwargs)
Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def create_tables() -> None:
    """Local SQLite (and the tests) only; PostgreSQL and SQL Server get their tables from `alembic upgrade head`."""
    if connection_string.startswith("sqlite"):
        MODEL_METADATA.create_all(engine)
