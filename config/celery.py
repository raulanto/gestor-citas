"""Celery configuration for agenda-citas project."""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("agenda")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
