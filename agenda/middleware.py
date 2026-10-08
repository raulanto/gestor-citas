"""Middleware for request ID tracing and structured access logging."""

import datetime
import logging
import re
import time
import uuid

from django.conf import settings
from django.http import HttpRequest, HttpResponse

from agenda.logging import (
    get_request_id,
    request_id_ctx_var,
    role_ctx_var,
    user_id_ctx_var,
)

SAFE_REQUEST_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
logger = logging.getLogger("agenda.requests")


class RequestIDMiddleware:
    """Extracts or generates an X-Request-ID header and propagates it in context and response."""

    def __init__(self, get_response) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        raw_header = request.headers.get("X-Request-ID")
        if not raw_header:
            raw_header = request.META.get("HTTP_X_REQUEST_ID")

        if raw_header and SAFE_REQUEST_ID_REGEX.match(raw_header):
            request_id = raw_header
        else:
            request_id = str(uuid.uuid4())

        token = request_id_ctx_var.set(request_id)
        request.request_id = request_id

        # Reset user and role in context for the new request
        user_token = user_id_ctx_var.set(None)
        role_token = role_ctx_var.set("ANONYMOUS")

        try:
            response = self.get_response(request)
            response["X-Request-ID"] = request_id
            return response
        finally:
            request_id_ctx_var.reset(token)
            user_id_ctx_var.reset(user_token)
            role_ctx_var.reset(role_token)


class RequestLogMiddleware:
    """Emits a single structured log entry for every HTTP request."""

    def __init__(self, get_response) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        skip_paths = getattr(
            settings,
            "LOG_SKIP_PATHS",
            ["/api/v1/health/", "/api/v1/health/ready/"],
        )
        if request.path in skip_paths:
            return self.get_response(request)

        start_time = time.monotonic()
        response = self.get_response(request)
        duration_ms = round((time.monotonic() - start_time) * 1000, 2)

        status_code = response.status_code
        if status_code >= 500:
            level = "ERROR"
        elif status_code >= 400:
            level = "WARNING"
        else:
            level = "INFO"

        # Determine user_id and role
        user_id = user_id_ctx_var.get()
        role = role_ctx_var.get()

        if user_id is None and hasattr(request, "user") and request.user.is_authenticated:
            user_id = request.user.pk
            is_staff = getattr(request.user, "is_staff", False)
            is_super = getattr(request.user, "is_superuser", False)
            if is_staff or is_super:
                role = "STAFF"
            else:
                role = "USER"

        extra_data = {
            "ts": datetime.datetime.now(datetime.UTC).isoformat(),
            "level": level,
            "request_id": get_request_id(),
            "method": request.method,
            "path": request.path,
            "status": status_code,
            "duration_ms": duration_ms,
            "user_id": user_id,
            "role": role,
        }

        # Log formatted request record
        if level == "ERROR":
            logger.error(
                f"{request.method} {request.path} -> {status_code} ({duration_ms}ms)",
                extra=extra_data,
            )
        elif level == "WARNING":
            logger.warning(
                f"{request.method} {request.path} -> {status_code} ({duration_ms}ms)",
                extra=extra_data,
            )
        else:
            logger.info(
                f"{request.method} {request.path} -> {status_code} ({duration_ms}ms)",
                extra=extra_data,
            )

        return response
