"""Test that all API routes deny anonymous access by default unless in the public whitelist."""

import re
import uuid
from collections.abc import Iterator

import pytest
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework import status
from rest_framework.test import APIClient

PUBLIC_WHITELIST = {
    ("GET", "/api/v1/health/"),
    ("GET", "/api/v1/health/ready/"),
    ("GET", "/api/v1/availability/"),
    ("POST", "/api/v1/appointments/"),
    ("POST", "/api/v1/auth/token/"),
    ("POST", "/api/v1/auth/token/refresh/"),
    ("POST", "/api/v1/auth/logout/"),
    ("GET", "/api/v1/schema/"),
    ("GET", "/api/v1/docs/"),
}


def _extract_routes(resolver: URLResolver, prefix: str = "") -> Iterator[tuple[str, object]]:
    for pattern in resolver.url_patterns:
        if isinstance(pattern, URLResolver):
            yield from _extract_routes(pattern, prefix + str(pattern.pattern))
        elif isinstance(pattern, URLPattern):
            yield prefix + str(pattern.pattern), pattern.callback


def _sample_url(pattern_str: str) -> str:
    """Replace path converters with sample concrete parameters."""
    url = pattern_str
    url = re.sub(r"<uuid:[^>]+>", str(uuid.uuid4()), url)
    url = re.sub(r"<int:exception_id>", "999", url)
    url = re.sub(r"<int:weekday>", "1", url)
    url = re.sub(r"<int:id>", "1", url)
    url = re.sub(r"<str:date>", "2026-10-15", url)
    url = re.sub(r"<[^>]+>", "1", url)
    if not url.startswith("/"):
        url = "/" + url
    return url


@pytest.mark.django_db
def test_all_api_routes_deny_anonymous_by_default(api_client: APIClient):
    """Crawl every route in /api/v1/ and assert anonymous requests are rejected."""
    resolver = get_resolver()
    all_routes = list(_extract_routes(resolver))

    api_routes = [
        (pattern, callback)
        for pattern, callback in all_routes
        if pattern.startswith("api/v1/") or pattern.startswith("/api/v1/")
    ]
    assert len(api_routes) >= 10, "Should have discovered all API routes"

    allowed_http_verbs = ["get", "post", "put", "patch", "delete"]
    checked_endpoints = []
    for pattern, callback in api_routes:
        sample_path = _sample_url(pattern)
        view_cls = getattr(callback, "view_class", None)
        if not view_cls:
            continue

        supported_verbs = getattr(view_cls, "http_method_names", allowed_http_verbs)
        http_methods = [
            m.upper()
            for m in supported_verbs
            if m.lower() in allowed_http_verbs and hasattr(view_cls, m.lower())
        ]

        for method in http_methods:
            is_whitelisted = (method, sample_path) in PUBLIC_WHITELIST
            checked_endpoints.append((method, sample_path, is_whitelisted))

            client_func = getattr(api_client, method.lower())
            response = client_func(sample_path)

            if is_whitelisted:
                assert response.status_code != status.HTTP_401_UNAUTHORIZED, (
                    f"Whitelisted endpoint {method} {sample_path} was denied with 401."
                )
            else:
                assert response.status_code in (
                    status.HTTP_401_UNAUTHORIZED,
                    status.HTTP_404_NOT_FOUND,
                ), (
                    f"Route {method} {sample_path} should reject unauthenticated access, "
                    f"got {response.status_code}"
                )

    assert len(checked_endpoints) >= 15
