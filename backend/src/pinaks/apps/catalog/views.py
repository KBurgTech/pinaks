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
from pinaks.apps.accounts.permissions import CanMutateDrafts, CanRead
from pinaks.apps.audit.services import request_correlation_id
from pinaks.apps.catalog.models import CatalogItem
from pinaks.apps.catalog.serializers import CatalogItemSerializer
from pinaks.apps.catalog.services import (
    CatalogCodeImmutableError,
    archive_catalog_item,
    create_catalog_item,
    search_catalog_items,
    update_catalog_item,
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


class CatalogItemListView(ReadOrMutatePermissionMixin, GenericAPIView[CatalogItem]):
    serializer_class = CatalogItemSerializer

    @extend_schema(
        operation_id="catalog_item_list",
        parameters=[
            OpenApiParameter("search", str),
            OpenApiParameter("archived", bool),
            OpenApiParameter("page", int),
            OpenApiParameter("page_size", int),
        ],
        responses={200: CatalogItemSerializer(many=True), 403: ErrorEnvelopeSerializer},
    )
    def get(self, request: Request) -> Response:
        archived = request.query_params.get("archived", "false").lower() == "true"
        items = search_catalog_items(
            search=request.query_params.get("search", ""), archived=archived
        )
        page = self.paginate_queryset(items)
        serializer = CatalogItemSerializer(page, many=True)  # type: ignore[arg-type]
        return self.get_paginated_response(serializer.data)

    @extend_schema(
        operation_id="catalog_item_create",
        request=CatalogItemSerializer,
        responses={
            201: CatalogItemSerializer,
            400: ErrorEnvelopeSerializer,
            403: ErrorEnvelopeSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = CatalogItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            item = create_catalog_item(
                values=serializer.validated_data,
                actor=_actor(request),
                correlation_id=request_correlation_id(request),
            )
        except DjangoValidationError as error:
            raise _validation_error(error) from error
        return Response(CatalogItemSerializer(item).data, status=status.HTTP_201_CREATED)


class CatalogItemDetailView(ReadOrMutatePermissionMixin, APIView):
    def _get_item(self, item_id: int) -> CatalogItem:
        try:
            return CatalogItem.objects.select_related("default_tax_profile").get(pk=item_id)
        except CatalogItem.DoesNotExist as error:
            raise NotFound("Catalog item was not found.") from error

    @extend_schema(
        operation_id="catalog_item_retrieve",
        responses={
            200: CatalogItemSerializer,
            403: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
        },
    )
    def get(self, _request: Request, item_id: int) -> Response:
        return Response(CatalogItemSerializer(self._get_item(item_id)).data)

    @extend_schema(
        operation_id="catalog_item_update",
        request=CatalogItemSerializer,
        responses={
            200: CatalogItemSerializer,
            400: ErrorEnvelopeSerializer,
            403: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
            409: ErrorEnvelopeSerializer,
        },
    )
    def patch(self, request: Request, item_id: int) -> Response:
        serializer = CatalogItemSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            item = update_catalog_item(
                item=self._get_item(item_id),
                values=serializer.validated_data,
                actor=_actor(request),
                correlation_id=request_correlation_id(request),
            )
        except CatalogCodeImmutableError as error:
            raise BusinessRuleViolation(
                code="catalog_code_immutable", message=str(error)
            ) from error
        except DjangoValidationError as error:
            raise _validation_error(error) from error
        return Response(CatalogItemSerializer(item).data)

    @extend_schema(
        operation_id="catalog_item_archive",
        responses={
            204: OpenApiResponse(description="Catalog item archived."),
            403: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
        },
    )
    def delete(self, request: Request, item_id: int) -> Response:
        archive_catalog_item(
            item=self._get_item(item_id),
            actor=_actor(request),
            correlation_id=request_correlation_id(request),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
