from django.db import transaction

from pinaks.apps.accounts.models import User, UserRole


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
