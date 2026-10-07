"""Development settings for agenda-citas project."""

from decouple import config

from .base import *  # noqa: F403

DEBUG = config("DEBUG", default=True, cast=bool)

# Optional SQLite override for lightweight local dev without PostgreSQL
if config("USE_SQLITE", default=False, cast=bool):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
        }
    }
