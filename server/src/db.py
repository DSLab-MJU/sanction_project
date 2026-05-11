from collections.abc import Generator
from urllib.parse import quote_plus

import psycopg
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    db_url: str | None = None
    postgres_user: str | None = None
    postgres_password: SecretStr | None = None
    postgres_db: str | None = None
    postgres_host: str = "sanction-postgres"
    postgres_port: int = 5432

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def resolved_db_url(self) -> str:
        if self.db_url:
            return self.db_url

        if self.postgres_user and self.postgres_password and self.postgres_db:
            password = quote_plus(self.postgres_password.get_secret_value())
            return (
                f"postgresql://{self.postgres_user}:{password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            )

        raise ValueError(
            "Set DB_URL or POSTGRES_USER, POSTGRES_PASSWORD, and POSTGRES_DB."
        )


settings = Settings()


def get_conn() -> psycopg.Connection:
    return psycopg.connect(settings.resolved_db_url, connect_timeout=5)


def get_db() -> Generator[psycopg.Connection, None, None]:
    conn = get_conn()
    try:
        yield conn
    finally:
        conn.close()
