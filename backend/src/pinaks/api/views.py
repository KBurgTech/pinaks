from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.reverse import reverse

from pinaks.api.serializers import (
    ApiRootSerializer,
    ErrorEnvelopeSerializer,
    ProbeSerializer,
)


@extend_schema(
    operation_id="api_root",
    responses={
        200: ApiRootSerializer,
        403: OpenApiResponse(
            response=ErrorEnvelopeSerializer,
            description="Authentication is required.",
        ),
    },
)
@api_view(["GET"])
def api_root(request: Request) -> Response:
    """Return discoverable links for the versioned product API."""
    return Response(
        {
            "probe": reverse("api-v1:probe", request=request),
            "schema": reverse("api-v1:schema", request=request),
        }
    )


@extend_schema(operation_id="probe", responses={200: ProbeSerializer})
@api_view(["GET"])
@permission_classes([AllowAny])
def probe(_request: Request) -> Response:
    """Confirm that the API process can serve requests without dependency checks."""
    return Response({"status": "ok", "checks": []})
