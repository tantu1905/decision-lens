"""Tests run on a fresh SQLite file and a local storage folder, with no Azure settings (stand-ins answer)."""
import os
import tempfile

TMP = tempfile.mkdtemp()
os.environ.update(DB_CONNECTION_STRING=f"sqlite:///{TMP}/test.db", LOCAL_STORAGE_DIR=f"{TMP}/storage",
                  FOUNDRY_ENDPOINT="", FOUNDRY_MODEL="", FOUNDRY_API_KEY="", DECISION1_ENDPOINT="", DECISION1_API_KEY="",
                  BLOB_CONNECTION_STRING="", ADMIN_TOKEN="", LOGGING_MODE="console", LOAD_SAMPLE_ON_START="true")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c
