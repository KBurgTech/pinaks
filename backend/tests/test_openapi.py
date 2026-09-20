from rest_framework.test import APIClient


def test_openapi_describes_versioned_paths_and_stable_error_schema() -> None:
    response = APIClient().get("/api/v1/schema/")

    assert response.status_code == 200
    schema = response.json()
    assert "/api/v1/" in schema["paths"]
    assert "/api/v1/probe/" in schema["paths"]
    assert "ErrorEnvelope" in schema["components"]["schemas"]
    assert schema["paths"]["/api/v1/"]["get"]["responses"]["403"] == {
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}},
        "description": "Authentication is required.",
    }
