from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
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
    TaxProfileSerializer,
)
from pinaks.apps.accounts.capabilities import ROLE_CAPABILITIES
from pinaks.apps.accounts.models import User, UserRole
from pinaks.apps.accounts.permissions import CanAdminister
from pinaks.apps.audit.services import request_correlation_id
from pinaks.apps.configuration.models import CompanyProfile, TaxProfile
from pinaks.apps.configuration.services import (
    get_feature_flags,
    save_company_profile,
    save_tax_profile,
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


def _save_tax_profile(
    request: Request, *, profile: TaxProfile | None = None, partial: bool = False
) -> Response:
    serializer = TaxProfileSerializer(data=request.data, partial=partial)
    serializer.is_valid(raise_exception=True)
    user = request.user
    assert isinstance(user, User)
    try:
        saved, created = save_tax_profile(
            profile=profile,
            values=serializer.validated_data,
            actor=user,
            correlation_id=request_correlation_id(request),
        )
    except DjangoValidationError as error:
        raise ValidationError(error.message_dict) from error
    response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return Response(TaxProfileSerializer(saved).data, status=response_status)


class TaxProfileListView(APIView):
    permission_classes = (CanAdminister,)

    @extend_schema(
        operation_id="tax_profile_list",
        responses={200: TaxProfileSerializer(many=True), 403: ErrorEnvelopeSerializer},
    )
    def get(self, _request: Request) -> Response:
        profiles = TaxProfile.objects.filter(is_current=True).order_by("code")
        # DRF's stubs do not model the queryset accepted when ``many=True``.
        serialized = TaxProfileSerializer(profiles, many=True)  # type: ignore[arg-type]
        return Response(serialized.data)

    @extend_schema(
        operation_id="tax_profile_create",
        request=TaxProfileSerializer,
        responses={
            201: TaxProfileSerializer,
            400: ErrorEnvelopeSerializer,
            403: ErrorEnvelopeSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        return _save_tax_profile(request)


class TaxProfileDetailView(APIView):
    permission_classes = (CanAdminister,)

    def _get_profile(self, profile_id: int) -> TaxProfile:
        try:
            return TaxProfile.objects.get(pk=profile_id)
        except TaxProfile.DoesNotExist as error:
            raise NotFound("Tax profile was not found.") from error

    @extend_schema(
        operation_id="tax_profile_retrieve",
        responses={
            200: TaxProfileSerializer,
            403: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
        },
    )
    def get(self, _request: Request, profile_id: int) -> Response:
        return Response(TaxProfileSerializer(self._get_profile(profile_id)).data)

    @extend_schema(
        operation_id="tax_profile_update",
        request=TaxProfileSerializer,
        responses={
            200: TaxProfileSerializer,
            201: TaxProfileSerializer,
            400: ErrorEnvelopeSerializer,
            403: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
        },
    )
    def patch(self, request: Request, profile_id: int) -> Response:
        return _save_tax_profile(request, profile=self._get_profile(profile_id), partial=True)
