from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración de la app. En producción DATABASE_URL apunta a PostgreSQL;
    en dev/test por defecto usamos SQLite en archivo para no requerir un servidor
    Postgres corriendo localmente. La lógica de dominio (cycle_service) es agnóstica
    del motor: solo usa SQLAlchemy Core/ORM estándar, sin SQL específico de Postgres.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./ciclos_dev.db"
    secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7
    default_currency: str = "MXN"
    default_timezone: str = "America/Mexico_City"
    cycle_months_ahead: int = 3


settings = Settings()
