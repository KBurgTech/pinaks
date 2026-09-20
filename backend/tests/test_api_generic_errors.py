import pytest
from django.test import override_settings
from django.urls import URLPattern, path
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIClient


@api_view(["GET"])
@permission_classes([AllowAny])
def permission_error_example(_request: Request) -> Response:
    raise PermissionDenied()


urlpatterns: list[URLPattern] = [
    path("permission-error/", permission_error_example),
]


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@override_settings(ROOT_URLCONF=__name__)
def test_framework_failure_uses_stable_error_envelope(api_client: APIClient) -> None:
    response = api_client.get("/permission-error/")

    assert response.status_code == 403
    assert response.json() == {
        "error": {
            "code": "permission_denied",
            "message": "You do not have permission to perform this action.",
            "fields": {},
        }
    }
