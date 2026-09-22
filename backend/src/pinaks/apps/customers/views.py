from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from pinaks.api.exceptions import BusinessRuleViolation
from pinaks.api.serializers import ErrorEnvelopeSerializer
from pinaks.apps.accounts.models import User
from pinaks.apps.accounts.permissions import CanAdminister, CanMutateDrafts, CanRead
from pinaks.apps.audit.services import request_correlation_id
from pinaks.apps.custom_fields.services import filter_custom_data, sensitive_custom_data
from pinaks.apps.customers.models import BillingRecipient, Customer
from pinaks.apps.customers.serializers import BillingRecipientSerializer, CustomerSerializer
from pinaks.apps.customers.services import (
    CustomerNumberImmutableError,
    archive_customer,
    create_billing_recipient,
    create_customer,
    search_customers,
    update_billing_recipient,
    update_customer,
)


class ReadOrMutatePermissionMixin:
    def get_permissions(self) -> list[BasePermission]:
        request = self.request  # type: ignore[attr-defined]
        permission_class = (
            CanRead if request.method in {"GET", "HEAD", "OPTIONS"} else CanMutateDrafts
        )
        return [permission_class()]


def _actor(request: Request) -> User:
    user = request.user
    assert isinstance(user, User)
    return user


def _validation_error(error: DjangoValidationError) -> ValidationError:
    if hasattr(error, "message_dict"):
        return ValidationError(error.message_dict)
    return ValidationError(error.messages)


class CustomerListView(ReadOrMutatePermissionMixin, GenericAPIView[Customer]):
    serializer_class = CustomerSerializer

    @extend_schema(
        operation_id="customer_list",
        parameters=[
            OpenApiParameter("search", str),
            OpenApiParameter("archived", bool),
            OpenApiParameter("page", int),
            OpenApiParameter("page_size", int),
            OpenApiParameter("custom_field", str),
            OpenApiParameter("custom_operator", str),
            OpenApiParameter("custom_value", str),
        ],
        responses={200: CustomerSerializer(many=True), 403: ErrorEnvelopeSerializer},
    )
    def get(self, request: Request) -> Response:
        archived = request.query_params.get("archived", "false").lower() == "true"
        customers = search_customers(
            search=request.query_params.get("search", ""), archived=archived
        )
        custom_field = request.query_params.get("custom_field")
        if custom_field:
            try:
                customers = filter_custom_data(
                    customers,
                    target="customer",
                    key=custom_field,
                    operator=request.query_params.get("custom_operator", "exact"),
                    value=request.query_params.get("custom_value", ""),
                )
            except DjangoValidationError as error:
                raise _validation_error(error) from error
        page = self.paginate_queryset(customers)
        serializer = CustomerSerializer(page, many=True)  # type: ignore[arg-type]
        return self.get_paginated_response(serializer.data)

    @extend_schema(
        operation_id="customer_create",
        request=CustomerSerializer,
        responses={
            201: CustomerSerializer,
            400: ErrorEnvelopeSerializer,
            403: ErrorEnvelopeSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = CustomerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            customer = create_customer(
                values=serializer.validated_data,
                actor=_actor(request),
                correlation_id=request_correlation_id(request),
            )
        except DjangoValidationError as error:
            raise _validation_error(error) from error
        return Response(CustomerSerializer(customer).data, status=status.HTTP_201_CREATED)


class CustomerDetailView(ReadOrMutatePermissionMixin, APIView):
    def _get_customer(self, customer_id: int) -> Customer:
        try:
            return Customer.objects.prefetch_related("addresses").get(pk=customer_id)
        except Customer.DoesNotExist as error:
            raise NotFound("Customer was not found.") from error

    @extend_schema(
        operation_id="customer_retrieve",
        responses={
            200: CustomerSerializer,
            403: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
        },
    )
    def get(self, _request: Request, customer_id: int) -> Response:
        return Response(CustomerSerializer(self._get_customer(customer_id)).data)

    @extend_schema(
        operation_id="customer_update",
        request=CustomerSerializer,
        responses={
            200: CustomerSerializer,
            400: ErrorEnvelopeSerializer,
            403: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
            409: ErrorEnvelopeSerializer,
        },
    )
    def patch(self, request: Request, customer_id: int) -> Response:
        serializer = CustomerSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            customer = update_customer(
                customer=self._get_customer(customer_id),
                values=serializer.validated_data,
                actor=_actor(request),
                correlation_id=request_correlation_id(request),
            )
        except CustomerNumberImmutableError as error:
            raise BusinessRuleViolation(
                code="customer_number_immutable", message=str(error)
            ) from error
        except DjangoValidationError as error:
            raise _validation_error(error) from error
        return Response(CustomerSerializer(customer).data)

    @extend_schema(
        operation_id="customer_archive",
        responses={
            204: OpenApiResponse(description="Customer archived."),
            403: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
        },
    )
    def delete(self, request: Request, customer_id: int) -> Response:
        archive_customer(
            customer=self._get_customer(customer_id),
            actor=_actor(request),
            correlation_id=request_correlation_id(request),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class BillingRecipientListView(ReadOrMutatePermissionMixin, APIView):
    def _get_customer(self, customer_id: int) -> Customer:
        try:
            return Customer.objects.get(pk=customer_id)
        except Customer.DoesNotExist as error:
            raise NotFound("Customer was not found.") from error

    @extend_schema(
        operation_id="billing_recipient_list",
        responses={200: BillingRecipientSerializer(many=True), 403: ErrorEnvelopeSerializer},
    )
    def get(self, _request: Request, customer_id: int) -> Response:
        recipients = self._get_customer(customer_id).billing_recipients.all()
        return Response(
            BillingRecipientSerializer(recipients, many=True).data  # type: ignore[arg-type]
        )

    @extend_schema(
        operation_id="billing_recipient_create",
        request=BillingRecipientSerializer,
        responses={
            201: BillingRecipientSerializer,
            400: ErrorEnvelopeSerializer,
            403: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
        },
    )
    def post(self, request: Request, customer_id: int) -> Response:
        serializer = BillingRecipientSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            recipient = create_billing_recipient(
                customer=self._get_customer(customer_id),
                values=serializer.validated_data,
                actor=_actor(request),
                correlation_id=request_correlation_id(request),
            )
        except DjangoValidationError as error:
            raise _validation_error(error) from error
        return Response(BillingRecipientSerializer(recipient).data, status=status.HTTP_201_CREATED)


class BillingRecipientDetailView(ReadOrMutatePermissionMixin, APIView):
    def _get_recipient(self, customer_id: int, recipient_id: int) -> BillingRecipient:
        try:
            return BillingRecipient.objects.get(pk=recipient_id, customer_id=customer_id)
        except BillingRecipient.DoesNotExist as error:
            raise NotFound("Billing recipient was not found.") from error

    @extend_schema(
        operation_id="billing_recipient_retrieve",
        responses={
            200: BillingRecipientSerializer,
            403: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
        },
    )
    def get(self, _request: Request, customer_id: int, recipient_id: int) -> Response:
        return Response(
            BillingRecipientSerializer(self._get_recipient(customer_id, recipient_id)).data
        )

    @extend_schema(
        operation_id="billing_recipient_update",
        request=BillingRecipientSerializer,
        responses={
            200: BillingRecipientSerializer,
            400: ErrorEnvelopeSerializer,
            403: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
        },
    )
    def patch(self, request: Request, customer_id: int, recipient_id: int) -> Response:
        serializer = BillingRecipientSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            recipient = update_billing_recipient(
                recipient=self._get_recipient(customer_id, recipient_id),
                values=serializer.validated_data,
                actor=_actor(request),
                correlation_id=request_correlation_id(request),
            )
        except DjangoValidationError as error:
            raise _validation_error(error) from error
        return Response(BillingRecipientSerializer(recipient).data)


class SensitiveCustomerFieldsView(APIView):
    permission_classes = (CanAdminister,)

    @extend_schema(
        operation_id="customer_sensitive_fields",
        responses={200: dict, 403: ErrorEnvelopeSerializer},
    )
    def get(self, request: Request, customer_id: int) -> Response:
        try:
            instance = Customer.objects.get(pk=customer_id)
        except Customer.DoesNotExist as error:
            raise NotFound("Record was not found.") from error
        return Response(
            sensitive_custom_data(
                target="customer",
                instance=instance,
                actor=_actor(request),
                correlation_id=request_correlation_id(request),
            )
        )
