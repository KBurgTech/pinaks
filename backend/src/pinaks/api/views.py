from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.views import APIView

from pinaks.api.serializers import (
    ApiRootSerializer,
    CapabilitiesSerializer,
    CompanyProfileSerializer,
    ErrorEnvelopeSerializer,
    ProbeSerializer,
)
from pinaks.apps.accounts.capabilities import ROLE_CAPABILITIES
from pinaks.apps.accounts.models import User, UserRole
from pinaks.apps.accounts.permissions import CanAdminister
from pinaks.apps.audit.services import request_correlation_id
from pinaks.apps.configuration.models import CompanyProfile
from pinaks.apps.configuration.services import get_feature_flags, save_company_profile


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
            "capabilities": reverse("api-v1:capabilities", request=request),
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


@extend_schema(operation_id="capabilities", responses={200: CapabilitiesSerializer})
@api_view(["GET"])
def capabilities(request: Request) -> Response:
    """Return backend-authoritative role capabilities and installed feature flags."""
    user = request.user
    assert isinstance(user, User)
    role = UserRole(user.role)
    return Response(
        {
            "role": role.value,
            "capabilities": ROLE_CAPABILITIES[role],
            "features": get_feature_flags(),
        }
    )


class CompanyProfileView(APIView):
    permission_classes = (CanAdminister,)

    @extend_schema(
        operation_id="company_profile_retrieve",
        responses={
            200: CompanyProfileSerializer,
            403: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
        },
    )
    def get(self, _request: Request) -> Response:
        profile = CompanyProfile.objects.first()
        if profile is None:
            raise NotFound("Company configuration has not been created.")
        return Response(CompanyProfileSerializer(profile).data)

    @extend_schema(
        operation_id="company_profile_replace",
        request=CompanyProfileSerializer,
        responses={
            200: CompanyProfileSerializer,
            201: CompanyProfileSerializer,
            400: ErrorEnvelopeSerializer,
            403: ErrorEnvelopeSerializer,
        },
    )
    def put(self, request: Request) -> Response:
        return self._save(request, partial=False)

    @extend_schema(
        operation_id="company_profile_update",
        request=CompanyProfileSerializer,
        responses={
            200: CompanyProfileSerializer,
            400: ErrorEnvelopeSerializer,
            403: ErrorEnvelopeSerializer,
        },
    )
    def patch(self, request: Request) -> Response:
        return self._save(request, partial=True)

    def _save(self, request: Request, *, partial: bool) -> Response:
        serializer = CompanyProfileSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        user = request.user
        assert isinstance(user, User)
        profile, created = save_company_profile(
            values=serializer.validated_data,
            actor=user,
            correlation_id=request_correlation_id(request),
        )
        response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(CompanyProfileSerializer(profile).data, status=response_status)
