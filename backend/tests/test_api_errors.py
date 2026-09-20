import pytest
from django.test import override_settings
from django.urls import URLPattern, path
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIClient


class ExampleInputSerializer(serializers.Serializer[dict[str, str]]):
    name = serializers.CharField()


@api_view(["POST"])
@permission_classes([AllowAny])
def field_error_example(request: Request) -> Response:
    serializer = ExampleInputSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return Response(serializer.validated_data)


urlpatterns: list[URLPattern] = [
    path("field-error/", field_error_example),
]


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@override_settings(ROOT_URLCONF=__name__)
def test_field_validation_uses_stable_error_envelope(api_client: APIClient) -> None:
    response = api_client.post("/field-error/", data={}, format="json")

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "validation_error",
            "message": "Request validation failed.",
            "fields": {
                "name": [
                    {"code": "required", "message": "This field is required."},
                ]
            },
        }
    }
