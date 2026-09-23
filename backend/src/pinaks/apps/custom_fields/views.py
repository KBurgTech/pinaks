from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from pinaks.api.exceptions import BusinessRuleViolation
from pinaks.api.serializers import ErrorEnvelopeSerializer
from pinaks.apps.accounts.models import User
from pinaks.apps.accounts.permissions import CanAdminister, CanRead
from pinaks.apps.audit.services import request_correlation_id
from pinaks.apps.custom_fields.models import CustomFieldDefinition
from pinaks.apps.custom_fields.serializers import CustomFieldDefinitionSerializer
from pinaks.apps.custom_fields.services import (
    DefinitionKeyImmutableError,
    definitions_for_target,
    publish_definition,
    retire_definition,
    update_definition,
)


def _actor(request: Request) -> User:
    assert isinstance(request.user, User)
    return request.user


def _raise_validation(error: DjangoValidationError) -> None:
    raise ValidationError(
        error.message_dict if hasattr(error, "message_dict") else error.messages
    ) from error


class DefinitionPermissionMixin:
    def get_permissions(self) -> list[BasePermission]:
        request = self.request  # type: ignore[attr-defined]
        return [(CanRead if request.method in {"GET", "HEAD", "OPTIONS"} else CanAdminister)()]


class DefinitionListView(DefinitionPermissionMixin, APIView):
    @extend_schema(
        operation_id="custom_field_definition_list",
        parameters=[OpenApiParameter("target", str)],
        responses={200: CustomFieldDefinitionSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        target = request.query_params.get("target", "")
        if target not in {"customer", "catalog_item", "invoice", "invoice_line"}:
            raise ValidationError({"target": "Choose customer or catalog_item."})
        serializer = CustomFieldDefinitionSerializer(
            definitions_for_target(target=target),  # type: ignore[arg-type]
            many=True,
        )
        return Response(serializer.data)

    @extend_schema(
        operation_id="custom_field_definition_create",
        request=CustomFieldDefinitionSerializer,
        responses={
            201: CustomFieldDefinitionSerializer,
            400: ErrorEnvelopeSerializer,
            403: ErrorEnvelopeSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = CustomFieldDefinitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            field = publish_definition(
                values=serializer.validated_data,
                actor=_actor(request),
                correlation_id=request_correlation_id(request),
            )
        except DjangoValidationError as error:
            _raise_validation(error)
        return Response(CustomFieldDefinitionSerializer(field).data, status=status.HTTP_201_CREATED)


class DefinitionDetailView(DefinitionPermissionMixin, APIView):
    def _get_field(self, field_id: int) -> CustomFieldDefinition:
        try:
            return CustomFieldDefinition.objects.get(pk=field_id)
        except CustomFieldDefinition.DoesNotExist as error:
            raise NotFound("Custom field was not found.") from error

    @extend_schema(
        operation_id="custom_field_definition_retrieve",
        responses={200: CustomFieldDefinitionSerializer},
    )
    def get(self, _request: Request, field_id: int) -> Response:
        return Response(CustomFieldDefinitionSerializer(self._get_field(field_id)).data)

    @extend_schema(
        operation_id="custom_field_definition_update",
        request=CustomFieldDefinitionSerializer,
        responses={
            200: CustomFieldDefinitionSerializer,
            400: ErrorEnvelopeSerializer,
            409: ErrorEnvelopeSerializer,
        },
    )
    def patch(self, request: Request, field_id: int) -> Response:
        serializer = CustomFieldDefinitionSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            field = update_definition(
                field=self._get_field(field_id),
                values=serializer.validated_data,
                actor=_actor(request),
                correlation_id=request_correlation_id(request),
            )
        except DefinitionKeyImmutableError as error:
            raise BusinessRuleViolation(
                code="custom_field_identity_immutable", message=str(error)
            ) from error
        except DjangoValidationError as error:
            _raise_validation(error)
        return Response(CustomFieldDefinitionSerializer(field).data)

    @extend_schema(
        operation_id="custom_field_definition_retire",
        responses={204: OpenApiResponse(description="Definition retired.")},
    )
    def delete(self, request: Request, field_id: int) -> Response:
        retire_definition(
            field=self._get_field(field_id),
            actor=_actor(request),
            correlation_id=request_correlation_id(request),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
