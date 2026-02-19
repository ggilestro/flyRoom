"""Admin console configuration from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = "mysql+pymysql://flystocks:password@db/flystocks"

    # Admin auth
    admin_username: str = "admin"
    admin_password_hash: str = ""
    admin_secret_key: str = "change-this-to-a-secure-key"

    # DB credentials for mariadb-dump
    db_host: str = "db"
    db_user: str = "flystocks"
    db_password: str = ""
    db_name: str = "flystocks"

    # Public base URL of the main flyRoom app (for verification email links)
    app_base_url: str = "https://app.flyroom.net"

    # Backup / Cloudflare R2
    r2_endpoint_url: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = "flyroom-backups"
    backup_retention_days: int = 30
    backup_cron_secret: str = ""
    backup_encryption_key: str = ""  # base64-encoded 32-byte AES key (required)


settings = Settings()
