from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.storage import default_storage
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.generics import GenericAPIView
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from pinaks.api.exceptions import BusinessRuleViolation
from pinaks.api.serializers import ErrorEnvelopeSerializer
from pinaks.apps.accounts.models import User
from pinaks.apps.accounts.permissions import CanAdminister
from pinaks.apps.audit.services import request_correlation_id
from pinaks.apps.documents.models import (
    DocumentAsset,
    DocumentTemplate,
    DocumentTemplateVersion,
    PreviewArtifact,
)
from pinaks.apps.documents.preview_services import create_preview
from pinaks.apps.documents.renderer import PreviewRenderError
from pinaks.apps.documents.serializers import (
    AssetUploadSerializer,
    DocumentAssetSerializer,
    PreviewRequestSerializer,
    PreviewResponseSerializer,
    TemplateSerializer,
    TemplateVersionSerializer,
    TemplateVersionWriteSerializer,
    TemplateWriteSerializer,
)
from pinaks.apps.documents.services import (
    IncompleteTranslationsError,
    create_template,
    publish_template,
    save_version,
    store_asset,
)


def _validation(error: DjangoValidationError) -> ValidationError:
    return ValidationError(error.message_dict if hasattr(error, "message_dict") else error.messages)


def _template(template_id: int) -> DocumentTemplate:
    try:
        return DocumentTemplate.objects.prefetch_related("versions").get(pk=template_id)
    except DocumentTemplate.DoesNotExist as error:
        raise NotFound("Document template was not found.") from error


class TemplateListView(GenericAPIView[DocumentTemplate]):
    permission_classes = (CanAdminister,)
    serializer_class = TemplateSerializer
    pagination_class = None

    @extend_schema(
        operation_id="document_template_list", responses={200: TemplateSerializer(many=True)}
    )
    def get(self, _request: Request) -> Response:
        return Response(
            TemplateSerializer(
                DocumentTemplate.objects.prefetch_related("versions"), many=True
            ).data
        )

    @extend_schema(
        operation_id="document_template_create",
        request=TemplateWriteSerializer,
        responses={201: TemplateSerializer, 400: ErrorEnvelopeSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = TemplateWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        actor = request.user
        assert isinstance(actor, User)
        try:
            template = create_template(
                code=str(serializer.validated_data["code"]),
                name=str(serializer.validated_data["name"]),
                actor=actor,
                correlation_id=request_correlation_id(request),
            )
        except DjangoValidationError as error:
            raise _validation(error) from error
        return Response(TemplateSerializer(template).data, status=status.HTTP_201_CREATED)


class TemplateDetailView(GenericAPIView[DocumentTemplate]):
    permission_classes = (CanAdminister,)
    serializer_class = TemplateSerializer

    @extend_schema(operation_id="document_template_retrieve", responses={200: TemplateSerializer})
    def get(self, _request: Request, template_id: int) -> Response:
        return Response(TemplateSerializer(_template(template_id)).data)


class TemplateVersionListView(GenericAPIView[DocumentTemplateVersion]):
    permission_classes = (CanAdminister,)
    serializer_class = TemplateVersionSerializer

    @extend_schema(
        operation_id="document_template_version_create",
        request=TemplateVersionWriteSerializer,
        responses={201: TemplateVersionSerializer, 400: ErrorEnvelopeSerializer},
    )
    def post(self, request: Request, template_id: int) -> Response:
        serializer = TemplateVersionWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if "language" not in serializer.validated_data:
            raise ValidationError({"language": "This field is required."})
        actor = request.user
        assert isinstance(actor, User)
        try:
            version = save_version(
                template_id=template_id,
                values=serializer.validated_data,
                actor=actor,
                correlation_id=request_correlation_id(request),
            )
        except DocumentTemplate.DoesNotExist as error:
            raise NotFound("Document template was not found.") from error
        except DjangoValidationError as error:
            raise _validation(error) from error
        return Response(TemplateVersionSerializer(version).data, status=status.HTTP_201_CREATED)


class TemplateVersionDetailView(GenericAPIView[DocumentTemplateVersion]):
    permission_classes = (CanAdminister,)
    serializer_class = TemplateVersionSerializer

    @extend_schema(
        operation_id="document_template_version_update",
        request=TemplateVersionWriteSerializer,
        responses={200: TemplateVersionSerializer, 400: ErrorEnvelopeSerializer},
    )
    def patch(self, request: Request, template_id: int, version_id: int) -> Response:
        serializer = TemplateVersionWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        actor = request.user
        assert isinstance(actor, User)
        try:
            version = save_version(
                template_id=template_id,
                version_id=version_id,
                values=serializer.validated_data,
                actor=actor,
                correlation_id=request_correlation_id(request),
            )
        except (DocumentTemplate.DoesNotExist, DocumentTemplateVersion.DoesNotExist) as error:
            raise NotFound("Document template version was not found.") from error
        except DjangoValidationError as error:
            raise _validation(error) from error
        return Response(TemplateVersionSerializer(version).data)


class TemplatePublishView(GenericAPIView[DocumentTemplate]):
    permission_classes = (CanAdminister,)
    serializer_class = TemplateSerializer

    @extend_schema(
        operation_id="document_template_publish",
        request=None,
        responses={200: TemplateSerializer, 409: ErrorEnvelopeSerializer},
    )
    def post(self, request: Request, template_id: int) -> Response:
        actor = request.user
        assert isinstance(actor, User)
        try:
            publish_template(
                template_id=template_id, actor=actor, correlation_id=request_correlation_id(request)
            )
        except DocumentTemplate.DoesNotExist as error:
            raise NotFound("Document template was not found.") from error
        except IncompleteTranslationsError as error:
            raise BusinessRuleViolation(
                code="template_translations_incomplete", message=str(error)
            ) from error
        return Response(TemplateSerializer(_template(template_id)).data)


class TemplateAssetView(GenericAPIView[DocumentAsset]):
    permission_classes = (CanAdminister,)
    parser_classes = (MultiPartParser, FormParser)
    serializer_class = DocumentAssetSerializer

    @extend_schema(
        operation_id="document_template_asset_upload",
        request=AssetUploadSerializer,
        responses={201: DocumentAssetSerializer, 400: ErrorEnvelopeSerializer},
    )
    def post(self, request: Request, template_id: int) -> Response:
        serializer = AssetUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        actor = request.user
        assert isinstance(actor, User)
        try:
            asset = store_asset(
                template_id=template_id,
                uploaded=serializer.validated_data["file"],
                actor=actor,
                correlation_id=request_correlation_id(request),
            )
        except DocumentTemplate.DoesNotExist as error:
            raise NotFound("Document template was not found.") from error
        except DjangoValidationError as error:
            raise _validation(error) from error
        return Response(DocumentAssetSerializer(asset).data, status=status.HTTP_201_CREATED)


class TemplatePreviewView(APIView):
    permission_classes = (CanAdminister,)
    serializer_class = PreviewRequestSerializer

    @extend_schema(
        operation_id="document_template_preview",
        request=PreviewRequestSerializer,
        responses={201: PreviewResponseSerializer, 400: ErrorEnvelopeSerializer},
    )
    def post(self, request: Request, template_id: int) -> Response:
        serializer = PreviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        language = str(values["language"])
        version = (
            DocumentTemplateVersion.objects.filter(template_id=template_id, language=language)
            .order_by("-version")
            .first()
        )
        if version is None:
            if not DocumentTemplate.objects.filter(pk=template_id).exists():
                raise NotFound("Document template was not found.")
            raise ValidationError({"language": "No template version exists for this language."})
        invoice = None
        if "invoice_id" in values:
            from pinaks.apps.billing.models import Invoice

            invoice = (
                Invoice.objects.select_related("customer")
                .filter(pk=values["invoice_id"], lifecycle_status="DRAFT")
                .first()
            )
            if invoice is None:
                raise NotFound("Draft invoice was not found.")
        actor = request.user
        assert isinstance(actor, User)
        try:
            artifact = create_preview(
                version=version, actor=actor, invoice=invoice, output_format=str(values["format"])
            )
        except PreviewRenderError as error:
            raise BusinessRuleViolation(code="preview_render_failed", message=str(error)) from error
        url = reverse("api-v1:document-preview-detail", kwargs={"preview_id": artifact.pk})
        return Response(
            {"id": artifact.pk, "url": url, "expires_at": artifact.expires_at},
            status=status.HTTP_201_CREATED,
        )


class PreviewDetailView(APIView):
    permission_classes = (CanAdminister,)
    serializer_class = PreviewResponseSerializer

    @extend_schema(operation_id="document_preview_retrieve", responses={200: bytes})
    def get(self, _request: Request, preview_id: UUID) -> HttpResponse:
        artifact = PreviewArtifact.objects.filter(
            pk=preview_id, expires_at__gt=timezone.now()
        ).first()
        if artifact is None:
            raise NotFound("Preview was not found or has expired.")
        with default_storage.open(artifact.storage_key, "rb") as stored:
            payload = stored.read()
        response = HttpResponse(payload, content_type=artifact.content_type)
        response["Cache-Control"] = "no-store"
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = (
            "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'"
        )
        response["Content-Disposition"] = "inline"
        return response
