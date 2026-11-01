from rest_framework import serializers

from pinaks.apps.accounts.models import User, UserRole


class ManagedUserSerializer(serializers.ModelSerializer[User]):
    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "role",
            "is_active",
            "is_protected",
            "must_change_password",
        )
        read_only_fields = fields


class CreateUserSerializer(serializers.Serializer[dict[str, object]]):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=UserRole.choices, default=UserRole.READ_ONLY)
    temporary_password = serializers.CharField(
        write_only=True, trim_whitespace=False, max_length=4096
    )


class UserAccessSerializer(serializers.Serializer[dict[str, object]]):
    role = serializers.ChoiceField(choices=UserRole.choices, required=False)
    is_active = serializers.BooleanField(required=False)


class TemporaryPasswordSerializer(serializers.Serializer[dict[str, object]]):
    temporary_password = serializers.CharField(
        write_only=True, trim_whitespace=False, max_length=4096
    )


class LocalPasswordSerializer(serializers.Serializer[dict[str, object]]):
    current_password = serializers.CharField(
        required=False,
        default="",
        allow_blank=True,
        write_only=True,
        trim_whitespace=False,
        max_length=4096,
    )
    new_password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=4096)


class OperationResultSerializer(serializers.Serializer[dict[str, object]]):
    completed = serializers.BooleanField()


class ConnectionSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.IntegerField()
    provider = serializers.CharField()


class IdentityProviderSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.CharField()
    name = serializers.CharField()
    connect_url = serializers.CharField()


class AccountDetailsSerializer(serializers.Serializer[dict[str, object]]):
    username = serializers.CharField()
    has_password = serializers.BooleanField()
    must_change_password = serializers.BooleanField()
    connections = ConnectionSerializer(many=True)
    providers = IdentityProviderSerializer(many=True)
