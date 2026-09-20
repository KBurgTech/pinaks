import pytest
from django.conf import settings
from rest_framework.request import Request
from rest_framework.test import APIClient, APIRequestFactory

from pinaks.api.pagination import StandardPageNumberPagination


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


def test_api_root_rejects_unauthenticated_requests_with_stable_error(
    api_client: APIClient,
) -> None:
    response = api_client.get("/api/v1/")

    assert response.status_code == 403
    assert response.json() == {
        "error": {
            "code": "authentication_required",
            "message": "Authentication credentials were not provided.",
            "fields": {},
        }
    }


def test_probe_is_public_and_health_neutral(api_client: APIClient) -> None:
    response = api_client.get("/api/v1/probe/")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": [],
    }


def test_standard_pagination_has_a_stable_response_shape() -> None:
    request = Request(APIRequestFactory().get("/records/?page=2&page_size=2"))
    paginator = StandardPageNumberPagination()

    # DRF accepts sequences, while its third-party stubs constrain this method
    # to querysets. A sequence keeps this convention test model-free.
    page: list[str] | None = paginator.paginate_queryset(
        ["first", "second", "third"],  # type: ignore[arg-type]
        request,
    )
    assert page is not None
    response = paginator.get_paginated_response(page)

    assert response.data == {
        "count": 3,
        "next": None,
        "previous": "http://testserver/records/?page_size=2",
        "results": ["third"],
    }


def test_collection_query_parameter_conventions() -> None:
    assert settings.REST_FRAMEWORK["ORDERING_PARAM"] == "ordering"
    assert settings.REST_FRAMEWORK["SEARCH_PARAM"] == "search"
