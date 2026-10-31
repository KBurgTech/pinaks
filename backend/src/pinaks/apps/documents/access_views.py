from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from pinaks.api.exceptions import BusinessRuleViolation
from pinaks.api.serializers import ErrorEnvelopeSerializer
from pinaks.apps.accounts.permissions import CanRead
from pinaks.apps.billing.models import Invoice, LifecycleStatus
from pinaks.apps.documents.access import artifacts_healthy, read_artifact
from pinaks.apps.documents.issuance import ArtifactIntegrityError
from pinaks.apps.documents.models import IssuedArtifact
from pinaks.apps.workers.models import WorkItem


class ArtifactMetadataSerializer(serializers.ModelSerializer[IssuedArtifact]):
    class Meta:
        model = IssuedArtifact
        fields = (
            "kind",
            "sha256",
            "size",
            "standard",
            "profile",
            "specification_version",
            "generated_at",
        )


class DocumentStateSerializer(serializers.Serializer):
    lifecycle_status = serializers.CharField()
    operation_state = serializers.CharField(allow_null=True)
    failure_code = serializers.CharField()
    healthy = serializers.BooleanField()
    artifacts = ArtifactMetadataSerializer(many=True)


class InvoiceDocumentsView(APIView):
    permission_classes = (CanRead,)

    @extend_schema(
        operation_id="invoice_documents",
        responses={
            200: DocumentStateSerializer,
            403: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
        },
    )
    def get(self, request: Request, invoice_id: int) -> Response:
        invoice = get_object_or_404(Invoice, pk=invoice_id)
        artifacts = list(IssuedArtifact.objects.filter(invoice=invoice))
        operation = WorkItem.objects.filter(
            job_type="documents.generate", identity=str(invoice_id)
        ).first()
        return Response(
            {
                "lifecycle_status": invoice.lifecycle_status,
                "operation_state": operation.state if operation else None,
                "failure_code": operation.failure_code if operation else "",
                "healthy": invoice.lifecycle_status
                in (LifecycleStatus.ISSUED, LifecycleStatus.CANCELLED)
                and artifacts_healthy(artifacts),
                "artifacts": ArtifactMetadataSerializer(artifacts, many=True).data,
            },
            headers={"Cache-Control": "no-store"},
        )


class InvoiceArtifactView(APIView):
    permission_classes = (CanRead,)

    @extend_schema(
        operation_id="invoice_artifact_download",
        responses={
            200: bytes,
            403: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
            409: ErrorEnvelopeSerializer,
        },
    )
    def get(self, request: Request, invoice_id: int, kind: str) -> HttpResponse:
        artifact = get_object_or_404(
            IssuedArtifact,
            invoice_id=invoice_id,
            kind=kind,
            invoice__lifecycle_status__in=(LifecycleStatus.ISSUED, LifecycleStatus.CANCELLED),
        )
        try:
            data = read_artifact(artifact)
        except ArtifactIntegrityError as error:
            raise BusinessRuleViolation(
                code="artifact_integrity_failed",
                message="Issued artifact integrity verification failed.",
            ) from error
        mime, extension = {
            "pdf": ("application/pdf", "pdf"),
            "xml": ("application/xml", "xml"),
            "report": ("application/json", "json"),
        }[artifact.kind]
        response = HttpResponse(data, content_type=mime)
        response["Content-Disposition"] = (
            f'attachment; filename="invoice-{invoice_id}-{kind}.{extension}"'
        )
        response["Cache-Control"] = "no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
