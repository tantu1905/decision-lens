"""Settings read from environment variables or backend/.env (pydantic-settings). Keys never live in the code.
Every outside service has a local stand-in, so an empty .env still runs the whole flow."""
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
LOCAL_DB = f"sqlite:///{BACKEND / 'decision_lens.db'}"
LOCAL_STORAGE = str(BACKEND / "storage")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND / ".env", extra="ignore")

    # database: SQLite locally, Azure SQL ("Server=...;Database=...") in the cloud
    db_connection_string: str = LOCAL_DB
    # Azure AI Foundry + Microsoft Agent Framework
    foundry_endpoint: str = ""              # the Foundry resource, e.g. https://<name>.services.ai.azure.com
    foundry_model: str = ""                 # the GPT deployment name
    foundry_light_model: str = ""           # a smaller GPT deployment for the text-only agents (empty: foundry_model)
    foundry_api_key: str = ""
    # Microsoft Decision-1 (usually the same resource and key)
    decision1_endpoint: str = ""
    decision1_deployment: str = ""
    decision1_api_key: str = ""
    # Azure Blob Storage (empty: files go to local_storage_dir)
    blob_connection_string: str = ""
    blob_container: str = "decision-lens"
    local_storage_dir: str = LOCAL_STORAGE
    # flow
    max_parallel: int = 8                   # agent calls at the same time (Foundry rate limit)
    agent_timeout_s: int = 120
    # logging: console locally; azure sends logs and traces to Application Insights
    logging_mode: str = "console"
    app_insights_connection_string: str | None = Field(
        default=None,
        validation_alias=AliasChoices("APPLICATIONINSIGHTS_CONNECTION_STRING", "app_insights_connection_string"),
    )
    deployment_environment: str = "development"
    service_version: str = "2.0.0"
    telemetry_sampling_ratio: float = 1.0
    agent_telemetry_mode: str = "critical"      # critical / info / verbose (verbose also records prompts)
    # app
    sample_match_dir: str = str(REPO / "data" / "synthetic_match")
    frontend_dir: str = str(REPO / "frontend" / "dist")    # built by `npm run build` in frontend/
    load_sample_on_start: bool = False

    @field_validator("db_connection_string", "local_storage_dir")
    @classmethod
    def empty_means_local(cls, value: str, info) -> str:
        """An empty line in .env (DB_CONNECTION_STRING=) means the local SQLite file and storage folder."""
        if value.strip():
            return value.strip()
        return LOCAL_DB if info.field_name == "db_connection_string" else LOCAL_STORAGE

    @field_validator("logging_mode")
    @classmethod
    def validate_logging_mode(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"azure", "console"}:
            raise ValueError("logging_mode must be 'azure' or 'console'.")
        return value

    @field_validator("agent_telemetry_mode")
    @classmethod
    def validate_agent_telemetry_mode(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"verbose", "info", "critical"}:
            raise ValueError("agent_telemetry_mode must be 'verbose', 'info', or 'critical'.")
        return value

    @field_validator("telemetry_sampling_ratio")
    @classmethod
    def validate_sampling_ratio(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("telemetry_sampling_ratio must be between 0 and 1.")
        return value

    @property
    def foundry_ready(self) -> bool:
        return bool(self.foundry_endpoint and self.foundry_model and self.foundry_api_key)

    @property
    def decision1_ready(self) -> bool:
        return bool(self.decision1_endpoint and self.decision1_deployment and self.decision1_api_key)


settings = Settings()
