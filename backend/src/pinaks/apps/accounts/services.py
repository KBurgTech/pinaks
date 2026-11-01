from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework.exceptions import PermissionDenied, ValidationError

from pinaks.api.exceptions import BusinessRuleViolation
from pinaks.apps.accounts.models import User, UserRole
from pinaks.apps.audit.services import record_event


@transaction.atomic
def update_user_access(
    *,
    actor: User,
    user: User,
    role: UserRole | None = None,
    is_active: bool | None = None,
    correlation_id: str | None = None,
) -> User:
    """Change audited user access fields as one transaction."""
    # Serialize all access changes, including concurrent demotion of different admins.
    list(User.objects.select_for_update().filter(role=UserRole.ADMIN).order_by("pk"))
    require_admin(actor)
    user = User.objects.select_for_update().get(pk=user.pk)
    if user.is_protected and (role not in (None, UserRole.ADMIN) or is_active is False):
        raise BusinessRuleViolation(
            code="protected_administrator", message="A protected administrator cannot be changed."
        )
    if (
        user.role == UserRole.ADMIN
        and user.is_active
        and (role not in (None, UserRole.ADMIN) or is_active is False)
    ):
        if (
            not User.objects.filter(role=UserRole.ADMIN, is_active=True)
            .exclude(pk=user.pk)
            .exists()
        ):
            raise BusinessRuleViolation(
                code="last_administrator", message="The last administrator must remain active."
            )
    changed_fields: list[str] = []
    if role is not None and user.role != role:
        user.role = role
        changed_fields.append("role")
    if is_active is not None and user.is_active != is_active:
        user.is_active = is_active
        changed_fields.append("is_active")
    if changed_fields:
        user.save(
            update_fields=changed_fields,
            audit_actor=actor,
            audit_correlation_id=correlation_id,
        )
    return user


def require_admin(actor: User) -> None:
    if not User.objects.filter(pk=actor.pk, is_active=True, role=UserRole.ADMIN).exists():
        raise PermissionDenied()


def validate_local_password(password: str, user: User) -> None:
    try:
        validate_password(password, user)
    except DjangoValidationError as exc:
        raise ValidationError({"password": exc.messages}) from exc


@transaction.atomic
def create_local_user(
    *, actor: User, username: str, email: str, role: UserRole, temporary_password: str
) -> User:
    require_admin(actor)
    if User.objects.filter(email__iexact=email).exists():
        raise ValidationError({"email": ["The email address is already in use."]})
    user = User(username=username, email=email, role=role, must_change_password=True)
    validate_local_password(temporary_password, user)
    user.set_password(temporary_password)
    try:
        with transaction.atomic():
            user.full_clean()
            user.save()
    except (DjangoValidationError, IntegrityError) as exc:
        raise ValidationError(
            {"username": ["Account details are invalid or already in use."]}
        ) from exc
    record_event(
        actor=actor,
        action_code="account.created",
        target_type="accounts.user",
        target_identifier=str(user.pk),
    )
    return user


@transaction.atomic
def assign_temporary_password(*, actor: User, user: User, password: str) -> None:
    require_admin(actor)
    user = User.objects.select_for_update().get(pk=user.pk)
    if user.is_protected:
        raise BusinessRuleViolation(
            code="protected_administrator",
            message="Use the protected administrator's local password flow.",
        )
    validate_local_password(password, user)
    user.set_password(password)
    user.must_change_password = True
    user.save(update_fields=["password", "must_change_password"])
    record_event(
        actor=actor,
        action_code="account.temporary_password_assigned",
        target_type="accounts.user",
        target_identifier=str(user.pk),
    )


@transaction.atomic
def set_local_password(*, user: User, current_password: str, new_password: str) -> User:
    user = User.objects.select_for_update().get(pk=user.pk)
    if user.has_usable_password() and not user.check_password(current_password):
        raise ValidationError({"current_password": ["The current password is incorrect."]})
    validate_local_password(new_password, user)
    if user.check_password(new_password):
        raise ValidationError({"new_password": ["Choose a different password."]})
    user.set_password(new_password)
    user.must_change_password = False
    user.save(update_fields=["password", "must_change_password"])
    record_event(
        actor=user,
        action_code="account.password_changed",
        target_type="accounts.user",
        target_identifier=str(user.pk),
    )
    return user
