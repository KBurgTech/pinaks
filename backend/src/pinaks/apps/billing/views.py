from datetime import date

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
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
from pinaks.apps.billing.models import Invoice
from pinaks.apps.billing.serializers import DraftCreateSerializer, InvoiceSerializer
from pinaks.apps.billing.services import CompanyConfigurationMissingError, create_draft
from pinaks.apps.customers.models import Customer


def _filter_date(raw: str | None, field: str) -> date | None:
    if raw is None:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as error:
        raise ValidationError({field: "Use an ISO date."}) from error


class InvoiceListView(GenericAPIView[Invoice]):
    serializer_class = InvoiceSerializer

    def get_permissions(self) -> list[CanRead | CanMutateDrafts]:
        return [
            CanRead() if self.request.method in {"GET", "HEAD", "OPTIONS"} else CanMutateDrafts()
        ]

    @extend_schema(
        operation_id="invoice_list",
        parameters=[
            OpenApiParameter("customer", int),
            OpenApiParameter("lifecycle_status", str),
            OpenApiParameter("payment_status", str),
            OpenApiParameter("issue_date_from", str),
            OpenApiParameter("issue_date_to", str),
            OpenApiParameter("due_date_before", str),
            OpenApiParameter("due_date_after", str),
            OpenApiParameter("overdue", bool),
            OpenApiParameter("page", int),
            OpenApiParameter("page_size", int),
        ],
        responses={200: InvoiceSerializer(many=True), 403: ErrorEnvelopeSerializer},
    )
    def get(self, request: Request) -> Response:
        invoices = Invoice.objects.all()
        customer = request.query_params.get("customer")
        if customer is not None:
            if not customer.isdecimal():
                raise ValidationError({"customer": "Use a positive customer ID."})
            invoices = invoices.filter(customer_id=int(customer))
        for field, values in (
            ("lifecycle_status", ("DRAFT",)),
            ("payment_status", ("UNPAID", "PAID")),
        ):
            value = request.query_params.get(field)
            if value is not None:
                if value not in values:
                    raise ValidationError({field: "Unsupported filter value."})
                invoices = invoices.filter(**{field: value})
        for parameter, lookup in (
            ("issue_date_from", "issue_date__gte"),
            ("issue_date_to", "issue_date__lte"),
            ("due_date_before", "due_date__lt"),
            ("due_date_after", "due_date__gt"),
        ):
            filter_date = _filter_date(request.query_params.get(parameter), parameter)
            if filter_date is not None:
                invoices = invoices.filter(**{lookup: filter_date})
        overdue = request.query_params.get("overdue")
        if overdue is not None:
            if overdue not in ("true", "false"):
                raise ValidationError({"overdue": "Use true or false."})
            overdue_condition = Q(payment_status="UNPAID", due_date__lt=timezone.localdate())
            invoices = invoices.filter(
                overdue_condition if overdue == "true" else ~overdue_condition
            )
        page = self.paginate_queryset(invoices)
        serializer = InvoiceSerializer(page, many=True)  # type: ignore[arg-type]
        return self.get_paginated_response(serializer.data)

    @extend_schema(
        operation_id="invoice_create",
        request=DraftCreateSerializer,
        responses={
            201: InvoiceSerializer,
            400: ErrorEnvelopeSerializer,
            403: ErrorEnvelopeSerializer,
            409: ErrorEnvelopeSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = DraftCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            customer = Customer.objects.get(pk=values["customer_id"])
        except Customer.DoesNotExist as error:
            raise NotFound("Customer was not found.") from error
        actor = request.user
        assert isinstance(actor, User)
        try:
            invoice = create_draft(
                customer=customer,
                actor=actor,
                correlation_id=request_correlation_id(request),
                document_language=values.get("document_language"),
                issue_date=values.get("issue_date"),
                due_date=values.get("due_date"),
            )
        except CompanyConfigurationMissingError as error:
            raise BusinessRuleViolation(
                code="company_configuration_missing", message=str(error)
            ) from error
        except DjangoValidationError as error:
            raise ValidationError(
                error.message_dict if hasattr(error, "message_dict") else error.messages
            ) from error
        return Response(InvoiceSerializer(invoice).data, status=status.HTTP_201_CREATED)


class InvoiceDetailView(GenericAPIView[Invoice]):
    permission_classes = (CanRead,)
    serializer_class = InvoiceSerializer

    @extend_schema(
        operation_id="invoice_retrieve",
        responses={
            200: InvoiceSerializer,
            403: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
        },
    )
    def get(self, _request: Request, invoice_id: int) -> Response:
        try:
            invoice = Invoice.objects.get(pk=invoice_id)
        except Invoice.DoesNotExist as error:
            raise NotFound("Invoice was not found.") from error
        return Response(InvoiceSerializer(invoice).data)
