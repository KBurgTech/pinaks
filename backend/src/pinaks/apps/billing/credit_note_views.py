from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from pinaks.api.exceptions import BusinessRuleViolation
from pinaks.api.serializers import ErrorEnvelopeSerializer
from pinaks.apps.accounts.models import User
from pinaks.apps.accounts.permissions import CanIssueInvoices
from pinaks.apps.audit.services import request_correlation_id
from pinaks.apps.billing.credit_notes import InvalidCreditNoteError, create_credit_note
from pinaks.apps.billing.models import Invoice
from pinaks.apps.billing.serializers import InvoiceSerializer
from pinaks.apps.customers.serializers import StrictSerializer


class CreditLineSerializer(StrictSerializer[dict[str, object]]):
    position = serializers.IntegerField(min_value=1)
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=4, min_value=Decimal("0.0001")
    )
    unit_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.00")
    )


class CreditNoteSerializer(StrictSerializer[dict[str, object]]):
    reason = serializers.CharField(max_length=500)
    idempotency_key = serializers.CharField(max_length=100)
    lines = CreditLineSerializer(many=True, allow_empty=False)


class CreditNoteView(APIView):
    permission_classes = (CanIssueInvoices,)

    @extend_schema(
        request=CreditNoteSerializer,
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
        command = CreditNoteSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        actor = request.user
        assert isinstance(actor, User)
        try:
            invoice, created = create_credit_note(
                invoice_id=invoice_id,
                actor=actor,
                reason=command.validated_data["reason"],
                idempotency_key=command.validated_data["idempotency_key"],
                lines=command.validated_data["lines"],
                correlation_id=request_correlation_id(request),
            )
        except DjangoValidationError as error:
            raise ValidationError(error.message_dict) from error
        except Invoice.DoesNotExist as error:
            raise NotFound from error
        except InvalidCreditNoteError as error:
            raise BusinessRuleViolation(
                code="invalid_credit_note",
                message="Credit conflicts with the original invoice or existing reservations.",
            ) from error
        return Response(InvoiceSerializer(invoice).data, status=201 if created else 200)
