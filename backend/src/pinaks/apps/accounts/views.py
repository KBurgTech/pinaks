from django.contrib.auth import update_session_auth_hash
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from pinaks.apps.accounts.connections import account_details, disconnect_identity
from pinaks.apps.accounts.models import User, UserRole
from pinaks.apps.accounts.permissions import CanAdminister, CanRead
from pinaks.apps.accounts.serializers import (
    AccountDetailsSerializer,
    CreateUserSerializer,
    LocalPasswordSerializer,
    ManagedUserSerializer,
    OperationResultSerializer,
    TemporaryPasswordSerializer,
    UserAccessSerializer,
)
from pinaks.apps.accounts.services import (
    assign_temporary_password,
    create_local_user,
    set_local_password,
    update_user_access,
)


class UserListView(APIView):
    permission_classes = (CanAdminister,)

    @extend_schema(responses=ManagedUserSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(ManagedUserSerializer(User.objects.order_by("username"), many=True).data)

    @extend_schema(request=CreateUserSerializer, responses={201: ManagedUserSerializer})
    def post(self, request: Request) -> Response:
        serializer = CreateUserSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        assert isinstance(request.user, User)
        user = create_local_user(
            actor=request.user,
            username=data["username"],
            email=data["email"],
            role=UserRole(data["role"]),
            temporary_password=data["temporary_password"],
        )
        return Response(ManagedUserSerializer(user).data, status=201)


class UserDetailView(APIView):
    permission_classes = (CanAdminister,)

    @extend_schema(request=UserAccessSerializer, responses=ManagedUserSerializer)
    def patch(self, request: Request, user_id: int) -> Response:
        serializer = UserAccessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        assert isinstance(request.user, User)
        user = update_user_access(
            actor=request.user,
            user=get_object_or_404(User, pk=user_id),
            role=UserRole(data["role"]) if "role" in data else None,
            is_active=data.get("is_active"),
        )
        return Response(ManagedUserSerializer(user).data)


class TemporaryPasswordView(APIView):
    permission_classes = (CanAdminister,)

    @extend_schema(request=TemporaryPasswordSerializer, responses=OperationResultSerializer)
    def post(self, request: Request, user_id: int) -> Response:
        serializer = TemporaryPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assert isinstance(request.user, User)
        assign_temporary_password(
            actor=request.user,
            user=get_object_or_404(User, pk=user_id),
            password=serializer.validated_data["temporary_password"],
        )
        return Response({"completed": True})


class LocalPasswordView(APIView):
    permission_classes = (CanRead,)

    @extend_schema(request=LocalPasswordSerializer, responses=OperationResultSerializer)
    def post(self, request: Request) -> Response:
        serializer = LocalPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assert isinstance(request.user, User)
        user = set_local_password(user=request.user, **serializer.validated_data)
        update_session_auth_hash(request, user)
        return Response({"completed": True})


@method_decorator(ensure_csrf_cookie, name="dispatch")
class AccountDetailsView(APIView):
    permission_classes = (CanRead,)

    @extend_schema(responses=AccountDetailsSerializer)
    def get(self, request: Request) -> Response:
        assert isinstance(request.user, User)
        return Response(account_details(user=request.user, request=request))


class DisconnectIdentityView(APIView):
    permission_classes = (CanRead,)

    @extend_schema(request=None, responses=OperationResultSerializer)
    def post(self, request: Request, connection_id: int) -> Response:
        assert isinstance(request.user, User)
        disconnect_identity(user=request.user, connection_id=connection_id)
        return Response({"completed": True})
