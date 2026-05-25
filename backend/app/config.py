"""
Application configuration.

Loads environment variables from `.env` and exposes them as a typed
`settings` singleton. Importing this module is enough to validate that
every required key exists — pydantic raises ValidationError at import
time if any required field is missing.

Why this file exists: single source of truth for env vars. Instead of
scattering `os.getenv()` calls around the codebase, every module imports
`settings` and gets typed, validated access to all configuration.
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


# Locate the .env at the repo root regardless of where uvicorn is launched.
# Why absolute path: uvicorn is typically launched from `backend/`, while
# `.env` lives at the project root. A relative path would silently miss it.
_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    """
    Typed settings loaded from the `.env` file.

    Pydantic validates and coerces types automatically:
    "2" -> int 2, "true" -> bool True, etc.
    """

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        # Ignore variables that are not declared here (e.g. VITE_* frontend vars).
        extra="ignore",
    )

    # --- Anthropic (Claude) ---
    anthropic_api_key: str                                  # Required — no default
    claude_model: str = "claude-sonnet-4-6"                 # Overridable in .env

    # --- LangFuse (observability) ---
    langfuse_public_key: str = ""                           # Empty -> tracing disabled
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # --- Databricks SQL warehouse (read-only access to the dbt marts) ---
    # These reuse the same values that dbt and the ingestion script consume,
    # so the chatbot reads from the same warehouse the marts were built on.
    databricks_host: str                                    # Required
    databricks_token: str                                   # Required
    databricks_http_path: str                               # Required
    databricks_catalog: str = "analytics"
    # Schema the chatbot reads from. Default = dev for local sessions.
    # In deploy we override this to point at prod (olist_prod).
    databricks_chatbot_schema: str = "olist_dev"

    # --- Agent ---
    max_retries: int = 2                                    # SQL correction attempts

    # --- App ---
    app_env: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173"             # Comma-separated for multiple

    # --- Frontend ---
    vite_backend_url: str = "http://localhost:8000"         # Baked into Vite build


# Singleton: import `settings` from anywhere in the app.
# The instance is created once when this module is first loaded.
settings = Settings()
