import os
from dataclasses import dataclass


DEFAULT_DSN = "postgresql://" + "stonebreaker:stonebreaker" + "@localhost:5432/stonebreaker"  # dev-only


@dataclass(frozen=True)
class Settings:
    pg_dsn: str
    duckdb_path: str
    api_key: str
    max_rows: int = 100
    pg_statement_timeout_ms: int = 5000


def load_settings() -> Settings:
    api_key = os.environ.get("STONEBREAKER_API_KEY", "")
    if len(api_key) < 8:
        raise RuntimeError("STONEBREAKER_API_KEY must be set (min 8 chars); there is no default.")
    return Settings(
        pg_dsn=os.environ.get("STONEBREAKER_PG_DSN", DEFAULT_DSN),
        duckdb_path=os.environ.get("STONEBREAKER_DUCKDB_PATH", "./data/analytics.duckdb"),
        api_key=api_key,
    )
