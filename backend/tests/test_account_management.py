from collections.abc import Iterator

import pytest
from django.test import Client
from rest_framework.test import APIClient

from pinaks.apps.accounts.models import User, UserRole
from pinaks.apps.audit.models import AuditEvent

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin() -> User:
    return User.objects.create_user(username="admin", role=UserRole.ADMIN, password="old password")


@pytest.fixture
def api(admin: User) -> Iterator[APIClient]:
    client = APIClient()
    client.force_authenticate(admin)
    yield client


def test_admin_creates_user_with_temporary_password_and_safe_response(api: APIClient) -> None:
    response = api.post(
        "/api/v1/users/",
        {
            "username": "new-member",
            "email": "member@example.test",
            "role": "company_member",
            "temporary_password": "a temporary password for the new member",
        },
        format="json",
    )
    assert response.status_code == 201
    user = User.objects.get(username="new-member")
    assert user.role == UserRole.COMPANY_MEMBER
    assert user.must_change_password
    assert not user.is_staff and not user.is_superuser
    assert user.check_password("a temporary password for the new member")
    assert "password" not in response.json()
    assert AuditEvent.objects.filter(
        action_code="account.created", target_identifier=str(user.pk)
    ).exists()
    listing = api.get("/api/v1/users/")
    assert listing.status_code == 200
    assert "temporary password" not in str(listing.content)


@pytest.mark.parametrize("role", [UserRole.COMPANY_MEMBER, UserRole.READ_ONLY])
def test_non_admin_cannot_manage_users(role: UserRole) -> None:
    user = User.objects.create_user(username="member", role=role)
    api = APIClient()
    api.force_authenticate(user)
    assert api.get("/api/v1/users/").status_code == 403
    assert api.post("/api/v1/users/", {}, format="json").status_code == 403
    assert (
        api.patch(f"/api/v1/users/{user.pk}/", {"role": "admin"}, format="json").status_code == 403
    )
    assert (
        api.post(f"/api/v1/users/{user.pk}/temporary-password/", {}, format="json").status_code
        == 403
    )


def test_admin_changes_access_and_cannot_modify_protected_admin(api: APIClient) -> None:
    user = User.objects.create_user(username="member")
    response = api.patch(
        f"/api/v1/users/{user.pk}/", {"role": "company_member", "is_active": False}, format="json"
    )
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.role == UserRole.COMPANY_MEMBER and not user.is_active
    protected = User.objects.create_superuser(
        username="protected", password="local", is_protected=True
    )
    for payload in [{"role": "read_only"}, {"is_active": False}]:
        response = api.patch(f"/api/v1/users/{protected.pk}/", payload, format="json")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "protected_administrator"
    response = api.post(
        f"/api/v1/users/{protected.pk}/temporary-password/",
        {"temporary_password": "a sufficiently long temporary password"},
        format="json",
    )
    assert response.status_code == 409


def test_last_admin_cannot_be_demoted(api: APIClient, admin: User) -> None:
    response = api.patch(f"/api/v1/users/{admin.pk}/", {"role": "read_only"}, format="json")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "last_administrator"


def test_temporary_password_blocks_business_access_until_changed(api: APIClient) -> None:
    user = User.objects.create_user(
        username="member", password="original", role=UserRole.COMPANY_MEMBER
    )
    response = api.post(
        f"/api/v1/users/{user.pk}/temporary-password/",
        {"temporary_password": "temporary password must be changed"},
        format="json",
    )
    assert response.status_code == 200
    client = Client()
    assert client.login(username="member", password="temporary password must be changed")
    blocked = client.get("/api/v1/customers/")
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "password_change_required"
    assert client.get("/app/").headers["Location"] == "/app/account/"
    password_response = client.post(
        "/api/v1/account/password/",
        {
            "current_password": "temporary password must be changed",
            "new_password": "a replacement password for this account",
        },
        content_type="application/json",
    )
    assert password_response.status_code == 200
    user.refresh_from_db()
    assert not user.must_change_password
    assert user.check_password("a replacement password for this account")
    assert client.get("/api/v1/customers/").status_code == 200


def test_local_password_setup_and_validation() -> None:
    user = User.objects.create_user(username="external")
    api = APIClient()
    api.force_authenticate(user)
    assert (
        api.post("/api/v1/account/password/", {"new_password": "short"}, format="json").status_code
        == 400
    )
    assert (
        api.post(
            "/api/v1/account/password/",
            {"new_password": "a new local password for this account"},
            format="json",
        ).status_code
        == 200
    )
    assert (
        api.post(
            "/api/v1/account/password/",
            {"new_password": "a replacement password for this account"},
            format="json",
        ).status_code
        == 400
    )
    assert (
        api.post(
            "/api/v1/account/password/",
            {
                "current_password": "wrong",
                "new_password": "a replacement password for this account",
            },
            format="json",
        ).status_code
        == 400
    )


def test_account_mutations_require_csrf(admin: User) -> None:
    client = Client(enforce_csrf_checks=True)
    client.force_login(admin)
    assert client.post("/api/v1/users/", {}, content_type="application/json").status_code == 403
    assert (
        client.post("/api/v1/account/password/", {}, content_type="application/json").status_code
        == 403
    )


def test_invalid_or_duplicate_account_input_is_structured(api: APIClient) -> None:
    for payload in [
        {
            "username": "admin",
            "email": "admin@example.test",
            "temporary_password": "another sufficiently long password",
        },
        {"username": "weak", "email": "weak@example.test", "temporary_password": "short"},
        {
            "username": "invalid",
            "email": "bad",
            "temporary_password": "another sufficiently long password",
        },
    ]:
        response = api.post("/api/v1/users/", payload, format="json")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "validation_error"


def test_forced_password_change_allows_application_assets(api: APIClient) -> None:
    user = User.objects.create_user(
        username="forced", password="temporary", must_change_password=True
    )
    client = Client()
    client.force_login(user)
    assert client.get("/app/assets/main.js").status_code != 302


def test_admin_cannot_create_duplicate_email(api: APIClient, admin: User) -> None:
    admin.email = "local@example.test"
    admin.save()
    response = api.post(
        "/api/v1/users/",
        {
            "username": "duplicate",
            "email": "LOCAL@example.test",
            "temporary_password": "a long and valid temporary password",
        },
        format="json",
    )
    assert response.status_code == 400


def test_native_connections_surface_cannot_bypass_the_account_service(admin: User) -> None:
    client = Client()
    client.force_login(admin)
    assert client.post("/accounts/3rdparty/", {"account": "1"}).status_code == 405
    assert client.get("/accounts/3rdparty/").headers["Location"] == "/app/account/"


def test_account_details_supply_csrf_for_connection_forms(admin: User) -> None:
    client = Client(enforce_csrf_checks=True)
    client.force_login(admin)
    response = client.get("/api/v1/account/")
    assert response.status_code == 200
    assert "csrftoken" in response.cookies


def test_forced_password_change_cannot_reuse_password_through_native_form() -> None:
    password = "the original temporary password"
    user = User.objects.create_user(username="forced", password=password, must_change_password=True)
    client = Client()
    client.force_login(user)
    client.post(
        "/accounts/password/change/",
        {"oldpassword": password, "password1": password, "password2": password},
    )
    user.refresh_from_db()
    assert user.must_change_password
