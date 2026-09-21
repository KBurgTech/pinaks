import pytest
from django.contrib.admin.sites import AdminSite
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.test import Client, RequestFactory

from pinaks.apps.accounts.models import User, UserRole
from pinaks.apps.accounts.services import update_user_access
from pinaks.apps.audit.admin import AuditEventAdmin
from pinaks.apps.audit.models import AuditEvent
from pinaks.apps.audit.services import record_event

pytestmark = pytest.mark.django_db


def create_user(*, username: str, role: UserRole = UserRole.READ_ONLY) -> User:
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password="correct horse battery staple",
        role=role,
    )


def test_successful_local_authentication_records_a_safe_correlated_event() -> None:
    user = create_user(username="member", role=UserRole.COMPANY_MEMBER)

    response = Client().post(
        "/accounts/login/",
        {"login": "member", "password": "correct horse battery staple"},
        HTTP_X_REQUEST_ID="login-success-123",
    )

    assert response.status_code == 302
    event = AuditEvent.objects.get(action_code="authentication.login_succeeded")
    assert event.actor == user
    assert event.target_type == "accounts.user"
    assert event.target_identifier == str(user.pk)
    assert event.correlation_id == "login-success-123"
    assert event.metadata == {"authentication_method": "local"}


def test_failed_local_authentication_records_no_credentials_or_identifier() -> None:
    create_user(username="member")

    response = Client().post(
        "/accounts/login/",
        {"login": "member", "password": "definitely-wrong"},
        HTTP_X_REQUEST_ID="login-failure-456",
    )

    assert response.status_code == 200
    event = AuditEvent.objects.get(action_code="authentication.login_failed")
    assert event.actor is None
    assert event.target_type == "accounts.user"
    assert event.target_identifier == ""
    assert event.correlation_id == "login-failure-456"
    assert event.metadata == {"authentication_method": "local"}
    assert "member" not in str(event.metadata)
    assert "definitely-wrong" not in str(event.metadata)


def test_role_and_account_state_changes_are_recorded() -> None:
    administrator = create_user(username="administrator", role=UserRole.ADMIN)
    user = create_user(username="reader")

    update_user_access(
        actor=administrator,
        user=user,
        role=UserRole.COMPANY_MEMBER,
        is_active=False,
        correlation_id="access-change-789",
    )

    events = list(AuditEvent.objects.order_by("timestamp", "pk"))
    assert [event.action_code for event in events] == [
        "account.role_changed",
        "account.activation_changed",
    ]
    assert all(event.actor == administrator for event in events)
    assert all(event.target_type == "accounts.user" for event in events)
    assert all(event.target_identifier == str(user.pk) for event in events)
    assert all(event.correlation_id == "access-change-789" for event in events)
    assert events[0].metadata == {"old_role": "read_only", "new_role": "company_member"}
    assert events[1].metadata == {"was_active": True, "is_active": False}


def test_queryset_updates_cannot_bypass_access_change_auditing() -> None:
    user = create_user(username="reader")

    with pytest.raises(ValueError, match="audited access fields"):
        User.objects.filter(pk=user.pk).update(role=UserRole.COMPANY_MEMBER)

    user.refresh_from_db()
    assert user.role == UserRole.READ_ONLY
    assert not AuditEvent.objects.filter(action_code="account.role_changed").exists()


def test_events_are_append_only_through_application_and_admin_paths() -> None:
    actor = create_user(username="audited-actor")
    event = record_event(
        actor=actor,
        action_code="test.recorded",
        target_type="test.subject",
        target_identifier="123",
        correlation_id="test-correlation",
    )

    event.action_code = "test.tampered"
    with pytest.raises(ValueError, match="immutable"):
        event.save()
    with pytest.raises(ValueError, match="immutable"):
        event.delete()
    with pytest.raises(ValueError, match="immutable"):
        AuditEvent.objects.filter(pk=event.pk).update(action_code="test.tampered")
    with pytest.raises(ValueError, match="immutable"):
        AuditEvent.objects.filter(pk=event.pk).delete()
    with pytest.raises(ProtectedError):
        actor.delete()
    with pytest.raises(ValueError, match="record_event"):
        AuditEvent.objects.create(
            action_code="test.bypassed",
            target_type="test.subject",
            correlation_id="test-correlation",
        )

    admin = AuditEventAdmin(AuditEvent, AdminSite())
    request = RequestFactory().get("/admin/audit/auditevent/1/change/")
    request.user = create_user(username="admin", role=UserRole.ADMIN)
    request.user.is_superuser = True
    assert admin.has_view_permission(request, event)
    assert not admin.has_add_permission(request)
    assert not admin.has_change_permission(request, event)
    assert not admin.has_delete_permission(request, event)


@pytest.mark.parametrize(
    "metadata",
    [
        {"password": "raw-password"},
        {"request": {"authorization": "Bearer raw-token"}},
        {"email": "person@example.test"},
        {"invoice_contents": {"description": "private line item"}},
        {"custom_data": {"diagnosis": "sensitive"}},
    ],
)
def test_sensitive_metadata_cannot_be_recorded(metadata: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="prohibited sensitive key"):
        record_event(
            action_code="test.rejected",
            target_type="test.subject",
            correlation_id="test-correlation",
            metadata=metadata,
        )

    assert not AuditEvent.objects.filter(action_code="test.rejected").exists()
