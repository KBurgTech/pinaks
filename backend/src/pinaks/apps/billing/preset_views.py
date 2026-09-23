from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.generics import GenericAPIView
from rest_framework.request import Request
from rest_framework.response import Response

from pinaks.api.exceptions import BusinessRuleViolation
from pinaks.api.serializers import ErrorEnvelopeSerializer
from pinaks.apps.accounts.models import User
from pinaks.apps.accounts.permissions import CanMutateDrafts, CanRead
from pinaks.apps.audit.services import request_correlation_id
from pinaks.apps.billing.models import Invoice, InvoicePreset
from pinaks.apps.billing.presets import (
    ArchivedPresetError,
    apply_preset,
    archive_preset,
    create_preset,
    update_preset,
)
from pinaks.apps.billing.serializers import (
    ApplyPresetSerializer,
    InvoiceSerializer,
    PresetCreateSerializer,
    PresetSerializer,
    PresetWriteSerializer,
)
from pinaks.apps.billing.services import StaleInvoiceVersionError


def _validation(error: DjangoValidationError) -> ValidationError:
    return ValidationError(error.message_dict if hasattr(error, "message_dict") else error.messages)


class PresetListView(GenericAPIView[InvoicePreset]):
    serializer_class = PresetSerializer

    def get_permissions(self) -> list[CanRead | CanMutateDrafts]:
        return [CanRead() if self.request.method == "GET" else CanMutateDrafts()]

    @extend_schema(operation_id="preset_list", responses={200: PresetSerializer(many=True)})
    def get(self, _request: Request) -> Response:
        rows = list(InvoicePreset.objects.filter(is_archived=False))
        serializer = PresetSerializer(rows, many=True)  # type: ignore[arg-type]
        return Response(serializer.data)

    @extend_schema(
        operation_id="preset_create",
        request=PresetCreateSerializer,
        responses={201: PresetSerializer, 400: ErrorEnvelopeSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = PresetCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        actor = request.user
        assert isinstance(actor, User)
        try:
            preset = create_preset(
                values=serializer.validated_data,
                actor=actor,
                correlation_id=request_correlation_id(request),
            )
        except DjangoValidationError as error:
            raise _validation(error) from error
        return Response(PresetSerializer(preset).data, status=status.HTTP_201_CREATED)


class PresetDetailView(GenericAPIView[InvoicePreset]):
    serializer_class = PresetSerializer

    def get_permissions(self) -> list[CanRead | CanMutateDrafts]:
        return [CanRead() if self.request.method == "GET" else CanMutateDrafts()]

    @extend_schema(operation_id="preset_retrieve", responses={200: PresetSerializer})
    def get(self, _request: Request, preset_id: int) -> Response:
        try:
            preset = InvoicePreset.objects.get(pk=preset_id)
        except InvoicePreset.DoesNotExist as error:
            raise NotFound("Preset was not found.") from error
        return Response(PresetSerializer(preset).data)

    @extend_schema(
        operation_id="preset_update",
        request=PresetWriteSerializer,
        responses={200: PresetSerializer, 400: ErrorEnvelopeSerializer},
    )
    def patch(self, request: Request, preset_id: int) -> Response:
        serializer = PresetWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        actor = request.user
        assert isinstance(actor, User)
        try:
            preset = update_preset(
                preset_id=preset_id,
                values=serializer.validated_data,
                actor=actor,
                correlation_id=request_correlation_id(request),
            )
        except InvoicePreset.DoesNotExist as error:
            raise NotFound("Preset was not found.") from error
        except ArchivedPresetError as error:
            raise BusinessRuleViolation(code="preset_archived", message=str(error)) from error
        except DjangoValidationError as error:
            raise _validation(error) from error
        return Response(PresetSerializer(preset).data)


class PresetArchiveView(GenericAPIView[InvoicePreset]):
    def get_permissions(self) -> list[CanMutateDrafts]:
        return [CanMutateDrafts()]

    serializer_class = PresetSerializer

    @extend_schema(operation_id="preset_archive", request=None, responses={200: PresetSerializer})
    def post(self, request: Request, preset_id: int) -> Response:
        actor = request.user
        assert isinstance(actor, User)
        try:
            preset = archive_preset(
                preset_id=preset_id, actor=actor, correlation_id=request_correlation_id(request)
            )
        except InvoicePreset.DoesNotExist as error:
            raise NotFound("Preset was not found.") from error
        return Response(PresetSerializer(preset).data)


class ApplyPresetView(GenericAPIView[Invoice]):
    def get_permissions(self) -> list[CanMutateDrafts]:
        return [CanMutateDrafts()]

    serializer_class = InvoiceSerializer

    @extend_schema(
        operation_id="invoice_apply_preset",
        request=ApplyPresetSerializer,
        responses={
            200: InvoiceSerializer,
            400: ErrorEnvelopeSerializer,
            409: ErrorEnvelopeSerializer,
        },
    )
    def post(self, request: Request, invoice_id: int) -> Response:
        serializer = ApplyPresetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        actor = request.user
        assert isinstance(actor, User)
        try:
            invoice = apply_preset(
                invoice_id=invoice_id,
                preset_id=values["preset_id"],
                expected_version=values["expected_version"],
                mode=values["mode"],
                actor=actor,
                correlation_id=request_correlation_id(request),
            )
        except (Invoice.DoesNotExist, InvoicePreset.DoesNotExist) as error:
            raise NotFound("Invoice or preset was not found.") from error
        except ArchivedPresetError as error:
            raise BusinessRuleViolation(code="preset_archived", message=str(error)) from error
        except StaleInvoiceVersionError as error:
            raise BusinessRuleViolation(code="stale_invoice_version", message=str(error)) from error
        except DjangoValidationError as error:
            raise _validation(error) from error
        return Response(InvoiceSerializer(invoice).data)
