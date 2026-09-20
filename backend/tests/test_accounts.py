from io import StringIO

import pytest
from django.core.management import call_command
from django.db.models.deletion import ProtectedError
from django.test import Client, override_settings
from django.urls import path
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIClient

from pinaks.apps.accounts.models import User, UserRole
from pinaks.apps.accounts.permissions import CanMutateDrafts


@api_view(["POST"])
@permission_classes([CanMutateDrafts])
def draft_mutation_test_view(_request: Request) -> Response:
    return Response({"mutated": True})


urlpatterns = [path("draft-mutation/", draft_mutation_test_view)]


pytestmark = pytest.mark.django_db


def create_user(*, username: str, role: UserRole) -> User:
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password="correct horse battery staple",
        role=role,
    )


def test_local_user_has_stable_role_codes() -> None:
    assert [(role.value, role.label) for role in UserRole] == [
        ("admin", "Admin"),
        ("company_member", "Company Member"),
        ("read_only", "Read-Only"),
    ]

    user = create_user(username="reader", role=UserRole.READ_ONLY)

    assert user.role == UserRole.READ_ONLY
    assert user.has_usable_password()


def test_local_login_requires_csrf_and_creates_server_side_session() -> None:
    create_user(username="member", role=UserRole.COMPANY_MEMBER)
    client = Client(enforce_csrf_checks=True)

    rejected = client.post(
        "/accounts/login/",
        {"login": "member", "password": "correct horse battery staple"},
    )

    assert rejected.status_code == 403

    login_page = client.get("/accounts/login/")
    csrf_token = login_page.cookies["csrftoken"].value
    accepted = client.post(
        "/accounts/login/",
        {"login": "member", "password": "correct horse battery staple"},
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert accepted.status_code == 302
    assert "sessionid" in client.cookies
    assert client.session["_auth_user_id"]


def test_local_logout_requires_csrf_and_invalidates_the_session() -> None:
    user = create_user(username="member", role=UserRole.COMPANY_MEMBER)
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)

    rejected = client.post("/accounts/logout/")

    assert rejected.status_code == 403

    csrf_token = client.get("/accounts/logout/").cookies["csrftoken"].value
    accepted = client.post("/accounts/logout/", HTTP_X_CSRFTOKEN=csrf_token)

    assert accepted.status_code == 302
    assert "_auth_user_id" not in client.session


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (
            UserRole.ADMIN,
            {
                "read": True,
                "draft_mutation": True,
                "invoice_issuance": True,
                "payment_management": True,
                "administration": True,
            },
        ),
        (
            UserRole.COMPANY_MEMBER,
            {
                "read": True,
                "draft_mutation": True,
                "invoice_issuance": True,
                "payment_management": True,
                "administration": False,
            },
        ),
        (
            UserRole.READ_ONLY,
            {
                "read": True,
                "draft_mutation": False,
                "invoice_issuance": False,
                "payment_management": False,
                "administration": False,
            },
        ),
    ],
)
def test_capabilities_report_authenticated_role_boundaries(
    role: UserRole,
    expected: dict[str, bool],
) -> None:
    user = create_user(username=role.value, role=role)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/v1/capabilities/")

    assert response.status_code == 200
    assert response.json() == {
        "role": role.value,
        "capabilities": expected,
        "features": {
            "payment_requests": False,
            "reminders": False,
            "time_tracking": False,
        },
    }


def test_capabilities_reject_unauthenticated_requests() -> None:
    response = APIClient().get("/api/v1/capabilities/")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "authentication_required"


@override_settings(ROOT_URLCONF=__name__)
def test_read_only_user_cannot_mutate_through_a_direct_api_call() -> None:
    reader = create_user(username="reader", role=UserRole.READ_ONLY)
    member = create_user(username="member", role=UserRole.COMPANY_MEMBER)
    client = APIClient()

    client.force_authenticate(user=reader)
    rejected = client.post("/draft-mutation/", {}, format="json")

    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "permission_denied"

    client.force_authenticate(user=member)
    accepted = client.post("/draft-mutation/", {}, format="json")

    assert accepted.status_code == 200
    assert accepted.json() == {"mutated": True}


def test_bootstrap_admin_creates_an_idempotent_protected_local_administrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PINAKS_BOOTSTRAP_ADMIN_USERNAME", "breakglass")
    monkeypatch.setenv("PINAKS_BOOTSTRAP_ADMIN_EMAIL", "admin@example.test")
    monkeypatch.setenv(
        "PINAKS_BOOTSTRAP_ADMIN_PASSWORD",
        "a deliberately long bootstrap password",
    )
    output = StringIO()

    call_command("bootstrap_admin", stdout=output)

    administrator = User.objects.get(username="breakglass")
    assert administrator.role == UserRole.ADMIN
    assert administrator.is_active
    assert administrator.is_staff
    assert administrator.is_superuser
    assert administrator.is_protected
    assert administrator.check_password("a deliberately long bootstrap password")
    assert "a deliberately long bootstrap password" not in output.getvalue()

    original_password = administrator.password
    call_command("bootstrap_admin", stdout=output)
    administrator.refresh_from_db()

    assert administrator.password == original_password
    assert User.objects.filter(is_protected=True).count() == 1


def test_protected_administrator_cannot_be_demoted_deactivated_or_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PINAKS_BOOTSTRAP_ADMIN_USERNAME", "breakglass")
    monkeypatch.setenv("PINAKS_BOOTSTRAP_ADMIN_EMAIL", "admin@example.test")
    monkeypatch.setenv(
        "PINAKS_BOOTSTRAP_ADMIN_PASSWORD",
        "a deliberately long bootstrap password",
    )
    call_command("bootstrap_admin", stdout=StringIO())
    administrator = User.objects.get(username="breakglass")

    administrator.role = UserRole.READ_ONLY
    administrator.is_active = False
    administrator.is_staff = False
    administrator.is_superuser = False

    with pytest.raises(ValueError, match="protected administrator"):
        administrator.save()
    with pytest.raises(ProtectedError):
        administrator.delete()

    with pytest.raises(ProtectedError):
        User.objects.filter(pk=administrator.pk).delete()
    with pytest.raises(ValueError, match="protected administrator"):
        User.objects.filter(pk=administrator.pk).update(is_protected=False)


def test_public_self_registration_is_disabled() -> None:
    client = Client()

    response = client.post(
        "/accounts/signup/",
        {
            "username": "unapproved",
            "email": "unapproved@example.test",
            "password1": "a deliberately long signup password",
            "password2": "a deliberately long signup password",
        },
    )

    assert response.status_code == 200
    assert b"Sign Up Closed" in response.content
    assert not User.objects.filter(username="unapproved").exists()
