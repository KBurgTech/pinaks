from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from pinaks.api.exceptions import BusinessRuleViolation
from pinaks.api.serializers import ErrorEnvelopeSerializer
from pinaks.apps.accounts.models import User
from pinaks.apps.accounts.permissions import CanManagePayments
from pinaks.apps.audit.services import request_correlation_id
from pinaks.apps.billing.models import Invoice, PaymentStatus
from pinaks.apps.billing.payments import InvalidPaymentTransitionError, change_payment_status
from pinaks.apps.billing.serializers import InvoiceSerializer


class MarkPaidView(APIView):
    permission_classes = (CanManagePayments,)
    payment_status = PaymentStatus.PAID

    @extend_schema(
        request=None,
        responses={
            200: InvoiceSerializer,
            403: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
            409: ErrorEnvelopeSerializer,
        },
    )
    def post(self, request: Request, invoice_id: int) -> Response:
        actor = request.user
        assert isinstance(actor, User)
        try:
            invoice = change_payment_status(
                invoice_id=invoice_id,
                payment_status=self.payment_status,
                actor=actor,
                correlation_id=request_correlation_id(request),
            )
        except Invoice.DoesNotExist as error:
            raise NotFound from error
        except InvalidPaymentTransitionError as error:
            raise BusinessRuleViolation(
                code="invalid_payment_transition",
                message="Only issued invoices accept payment changes.",
            ) from error
        return Response(InvoiceSerializer(invoice).data)


class MarkUnpaidView(MarkPaidView):
    payment_status = PaymentStatus.UNPAID
