from collections.abc import Callable

from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from pinaks.api.exceptions import BusinessRuleViolation
from pinaks.api.serializers import ErrorEnvelopeSerializer
from pinaks.apps.accounts.models import User
from pinaks.apps.accounts.permissions import CanAdminister
from pinaks.apps.audit.services import request_correlation_id
from pinaks.apps.notifications.models import EmailTemplate
from pinaks.apps.notifications.serializers import EmailTemplateSerializer, EmailVersionSerializer
from pinaks.apps.notifications.services import (
    EmailConflictError,
    create_template,
    create_version,
    publish_template,
)


def email_operation[T](operation: Callable[[], T]) -> T:
    try:
        return operation()
    except ObjectDoesNotExist as error:
        raise NotFound from error
    except DjangoValidationError as error:
        raise ValidationError(
            error.message_dict if hasattr(error, "message_dict") else error.messages
        ) from error
    except EmailConflictError as error:
        raise BusinessRuleViolation(code="email_conflict", message=str(error)) from error


class EmailTemplateListView(APIView):
    permission_classes = (CanAdminister,)

    @extend_schema(
        responses={200: EmailTemplateSerializer(many=True), 403: ErrorEnvelopeSerializer}
    )
    def get(self, request: Request) -> Response:
        return Response(
            EmailTemplateSerializer(
                EmailTemplate.objects.prefetch_related("versions"), many=True
            ).data,
            headers={"Cache-Control": "no-store"},
        )

    @extend_schema(
        request=EmailTemplateSerializer,
        responses={
            201: EmailTemplateSerializer,
            400: ErrorEnvelopeSerializer,
            403: ErrorEnvelopeSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = EmailTemplateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        actor = request.user
        assert isinstance(actor, User)
        template = email_operation(
            lambda: create_template(
                code=serializer.validated_data["code"],
                name=serializer.validated_data["name"],
                actor=actor,
                correlation_id=request_correlation_id(request),
            )
        )
        return Response(EmailTemplateSerializer(template).data, status=201)


class EmailVersionView(APIView):
    permission_classes = (CanAdminister,)

    @extend_schema(
        request=EmailVersionSerializer,
        responses={
            201: EmailVersionSerializer,
            400: ErrorEnvelopeSerializer,
            403: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
        },
    )
    def post(self, request: Request, template_id: int) -> Response:
        serializer = EmailVersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        actor = request.user
        assert isinstance(actor, User)
        version = email_operation(
            lambda: create_version(
                template_id=template_id,
                language=serializer.validated_data["language"],
                subject=serializer.validated_data["subject"],
                body=serializer.validated_data["body"],
                actor=actor,
                correlation_id=request_correlation_id(request),
            )
        )
        return Response(EmailVersionSerializer(version).data, status=201)


class EmailPublishView(APIView):
    permission_classes = (CanAdminister,)

    @extend_schema(
        request=None,
        responses={
            200: EmailTemplateSerializer,
            403: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
            409: ErrorEnvelopeSerializer,
        },
    )
    def post(self, request: Request, template_id: int) -> Response:
        actor = request.user
        assert isinstance(actor, User)
        template = email_operation(
            lambda: publish_template(
                template_id=template_id, actor=actor, correlation_id=request_correlation_id(request)
            )
        )
        return Response(EmailTemplateSerializer(template).data)
