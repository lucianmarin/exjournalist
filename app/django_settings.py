import os
from pathlib import Path
from urllib.parse import urlparse

from app.config import DATABASE_URL

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
DEBUG = os.getenv("DEBUG", "1") == "1"
INSTALLED_APPS = [
    "app.apps.BlogAppConfig",
]
USE_TZ = True
TIME_ZONE = "UTC"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


def _database_config_from_url(url: str) -> dict:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()

    if scheme in {"postgres", "postgresql"}:
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/"),
            "USER": parsed.username or "",
            "PASSWORD": parsed.password or "",
            "HOST": parsed.hostname or "localhost",
            "PORT": str(parsed.port or 5432),
        }

    if scheme in {"sqlite", "sqlite3"}:
        db_path = parsed.path if parsed.path else "/db.sqlite3"
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": str(BASE_DIR / db_path.lstrip("/"))}

    raise ValueError(f"Unsupported DATABASE_URL scheme: {scheme}")


DATABASES = {
    "default": _database_config_from_url(DATABASE_URL),
}
