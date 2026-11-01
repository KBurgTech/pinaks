from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from pinaks.api.exceptions import BusinessRuleViolation
from pinaks.api.serializers import ErrorEnvelopeSerializer
from pinaks.apps.accounts.models import User
from pinaks.apps.accounts.permissions import CanIssueInvoices
from pinaks.apps.audit.services import request_correlation_id
from pinaks.apps.billing.models import Invoice
from pinaks.apps.billing.replacements import InvalidReplacementError, create_replacement
from pinaks.apps.billing.serializers import InvoiceSerializer
from pinaks.apps.customers.serializers import StrictSerializer


class CorrectInvoiceSerializer(StrictSerializer[dict[str, object]]):
    reason = serializers.CharField(max_length=500)
    idempotency_key = serializers.CharField(max_length=100)


class CorrectInvoiceView(APIView):
    permission_classes = (CanIssueInvoices,)

    @extend_schema(
        request=CorrectInvoiceSerializer,
        responses={
            200: InvoiceSerializer,
            201: InvoiceSerializer,
            400: ErrorEnvelopeSerializer,
            403: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
            409: ErrorEnvelopeSerializer,
        },
    )
    def post(self, request: Request, invoice_id: int) -> Response:
        command = CorrectInvoiceSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        actor = request.user
        assert isinstance(actor, User)
        try:
            invoice, created = create_replacement(
                invoice_id=invoice_id,
                actor=actor,
                reason=command.validated_data["reason"],
                idempotency_key=command.validated_data["idempotency_key"],
                correlation_id=request_correlation_id(request),
            )
        except Invoice.DoesNotExist as error:
            raise NotFound from error
        except InvalidReplacementError as error:
            raise BusinessRuleViolation(
                code="invalid_replacement",
                message="Replacement is unavailable or conflicts with an existing command.",
            ) from error
        return Response(InvoiceSerializer(invoice).data, status=201 if created else 200)
