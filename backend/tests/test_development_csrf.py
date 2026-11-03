"""Exercise browser origins forwarded by the local Vite proxy."""

import pytest
from django.http import HttpResponse
from django.middleware.csrf import CsrfViewMiddleware, get_token
from django.test import RequestFactory, override_settings

from pinaks.settings import development


@pytest.mark.parametrize(
    ("origin", "include_token", "expected_status"),
    [
        ("http://localhost:5173", True, 200),
        ("http://127.0.0.1:5173", True, 200),
        ("http://localhost:5173", False, 403),
        ("https://untrusted.example", True, 403),
    ],
)
def test_development_proxy_csrf(origin: str, include_token: bool, expected_status: int) -> None:
    request = RequestFactory().post("/accounts/login/", HTTP_ORIGIN=origin)
    if include_token:
        request.META["HTTP_X_CSRFTOKEN"] = get_token(request)
        request.COOKIES["csrftoken"] = request.META["CSRF_COOKIE"]

    def view(request: object) -> HttpResponse:
        return HttpResponse()

    with override_settings(
        ALLOWED_HOSTS=["testserver"],
        CSRF_TRUSTED_ORIGINS=getattr(development, "CSRF_TRUSTED_ORIGINS", []),
    ):
        middleware = CsrfViewMiddleware(view)
        middleware.process_request(request)
        response = middleware.process_view(request, view, (), {})

    assert (response.status_code if response is not None else 200) == expected_status
