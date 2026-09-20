import pytest
from django.test import override_settings
from django.urls import URLPattern, path
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIClient

from pinaks.api.exceptions import BusinessRuleViolation


@api_view(["POST"])
@permission_classes([AllowAny])
def business_error_example(_request: Request) -> Response:
    raise BusinessRuleViolation(
        code="record_not_editable",
        message="The record can no longer be edited.",
    )


urlpatterns: list[URLPattern] = [
    path("business-error/", business_error_example),
]


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@override_settings(ROOT_URLCONF=__name__)
def test_business_rule_failure_uses_stable_error_envelope(api_client: APIClient) -> None:
    response = api_client.post("/business-error/", data={}, format="json")

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "record_not_editable",
            "message": "The record can no longer be edited.",
            "fields": {},
        }
    }
