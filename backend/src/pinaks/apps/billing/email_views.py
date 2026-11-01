from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from pinaks.api.exceptions import BusinessRuleViolation
from pinaks.api.serializers import ErrorEnvelopeSerializer
from pinaks.apps.accounts.models import User
from pinaks.apps.accounts.permissions import CanMutateDrafts
from pinaks.apps.audit.services import request_correlation_id
from pinaks.apps.billing.emails import send_invoice
from pinaks.apps.billing.models import Invoice
from pinaks.apps.documents.issuance import ArtifactIntegrityError
from pinaks.apps.notifications.serializers import (
    EmailDefaultsSerializer,
    EmailDeliverySerializer,
    EmailSendSerializer,
    OutgoingEmailSerializer,
)
from pinaks.apps.notifications.services import delivery_history, published_templates
from pinaks.apps.notifications.views import email_operation


class SendInvoiceView(APIView):
    permission_classes = (CanMutateDrafts,)

    @extend_schema(
        responses={
            200: EmailDefaultsSerializer,
            403: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
        }
    )
    def get(self, request: Request, invoice_id: int) -> Response:
        invoice = get_object_or_404(Invoice.objects.select_related("customer"), pk=invoice_id)
        return Response(
            {
                "language": invoice.customer.preferred_language,
                "recipients": [invoice.customer.email] if invoice.customer.email else [],
                "templates": [
                    {"id": template.pk, "name": template.name} for template in published_templates()
                ],
            },
            headers={"Cache-Control": "no-store"},
        )

    @extend_schema(
        request=EmailSendSerializer,
        responses={
            201: OutgoingEmailSerializer,
            400: ErrorEnvelopeSerializer,
            403: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
            409: ErrorEnvelopeSerializer,
        },
    )
    def post(self, request: Request, invoice_id: int) -> Response:
        serializer = EmailSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        actor = request.user
        assert isinstance(actor, User)
        try:
            outgoing = email_operation(
                lambda: send_invoice(
                    invoice_id=invoice_id,
                    actor=actor,
                    correlation_id=request_correlation_id(request),
                    **serializer.validated_data,
                )
            )
        except ArtifactIntegrityError as error:
            raise BusinessRuleViolation(
                code="artifact_integrity_failed",
                message="Issued artifact integrity verification failed.",
            ) from error
        return Response(
            OutgoingEmailSerializer(outgoing).data,
            status=201,
            headers={"Cache-Control": "no-store"},
        )


class InvoiceEmailHistoryView(APIView):
    permission_classes = (CanMutateDrafts,)

    @extend_schema(
        responses={
            200: EmailDeliverySerializer(many=True),
            403: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
        }
    )
    def get(self, request: Request, invoice_id: int) -> Response:
        get_object_or_404(Invoice, pk=invoice_id)
        actor = request.user
        assert isinstance(actor, User)
        return Response(
            EmailDeliverySerializer(
                delivery_history(invoice_id=invoice_id, actor=actor), many=True
            ).data,
            headers={"Cache-Control": "no-store"},
        )
