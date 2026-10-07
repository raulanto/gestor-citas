"""Base settings for agenda-citas project."""

from pathlib import Path

from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config(
    "SECRET_KEY",
    default="django-insecure-change-me-in-production-random-key-12345",
)

DEBUG = config("DEBUG", default=False, cast=bool)

ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS",
    default="localhost,127.0.0.1,testserver",
    cast=Csv(),
)

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "agenda.apps.AgendaConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Database
DB_NAME = config("DB_NAME", default="agenda_db")
DB_USER = config("DB_USER", default="postgres")
DB_PASSWORD = config("DB_PASSWORD", default="postgres")
DB_HOST = config("DB_HOST", default="localhost")
DB_PORT = config("DB_PORT", default="5432")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": DB_NAME,
        "USER": DB_USER,
        "PASSWORD": DB_PASSWORD,
        "HOST": DB_HOST,
        "PORT": DB_PORT,
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Internationalization
LANGUAGE_CODE = "es-mx"
TIME_ZONE = "America/Mexico_City"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Django REST Framework
REST_FRAMEWORK = {
    "EXCEPTION_HANDLER": "agenda.api.exception_handler.custom_exception_handler",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}

# Business Rules / Domain Constants
BOOKING_MIN_ADVANCE_HOURS = config("BOOKING_MIN_ADVANCE_HOURS", default=2, cast=int)
BOOKING_MAX_ADVANCE_DAYS = config("BOOKING_MAX_ADVANCE_DAYS", default=60, cast=int)
CANCEL_MIN_HOURS = config("CANCEL_MIN_HOURS", default=4, cast=int)
MAX_RESCHEDULES_PER_APPOINTMENT = config("MAX_RESCHEDULES_PER_APPOINTMENT", default=2, cast=int)
MAX_ACTIVE_PER_REQUESTER_PER_DAY = config("MAX_ACTIVE_PER_REQUESTER_PER_DAY", default=1, cast=int)
WAITLIST_MAX_PER_DAY = config("WAITLIST_MAX_PER_DAY", default=20, cast=int)
DEFAULT_SLOT_STEP_MINUTES = config("DEFAULT_SLOT_STEP_MINUTES", default=15, cast=int)
WAITLIST_SWEEP_MINUTES = config("WAITLIST_SWEEP_MINUTES", default=5, cast=int)

# Celery Configuration
CELERY_BROKER_URL = config("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = config("CELERY_RESULT_BACKEND", default="redis://localhost:6379/0")
CELERY_TIMEZONE = TIME_ZONE
CELERY_ENABLE_UTC = True
CELERY_BEAT_SCHEDULE = {
    "waitlist-maintenance-sweep": {
        "task": "agenda.tasks.waitlist_maintenance_task",
        "schedule": WAITLIST_SWEEP_MINUTES * 60,
    },
}

