import json
import time
from collections.abc import Iterator
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
import requests
from allauth.socialaccount import models as social_models  # type: ignore[import-untyped]
from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpResponseBase
from django.test import Client, override_settings
from rest_framework.test import APIClient

from pinaks.apps.accounts.models import User, UserRole
from pinaks.apps.audit.models import AuditEvent

pytestmark = pytest.mark.django_db
ISSUER = "https://identity.example.test/application/o/pinaks/"
PROVIDER = "pinaks-test"
OIDC = {
    "openid_connect": {
        "APPS": [
            {
                "provider_id": PROVIDER,
                "name": "Test identity",
                "client_id": "pinaks-client",
                "secret": "server-secret",
                "settings": {
                    "server_url": ISSUER,
                    "fetch_userinfo": False,
                    "oauth_pkce_enabled": True,
                },
            }
        ]
    }
}


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, object]]:
    claims: dict[str, object] = {
        "sub": "subject-1",
        "email": "oidc@example.test",
        "email_verified": True,
        "preferred_username": "external",
        "groups": ["admin"],
    }

    def request(
        _session: requests.Session, method: str, url: str, **kwargs: object
    ) -> requests.Response:
        response = requests.Response()
        response.status_code = 200
        response.headers["content-type"] = "application/json"
        response.url = url
        if url.endswith("/.well-known/openid-configuration"):
            data = {
                "issuer": ISSUER,
                "authorization_endpoint": ISSUER + "authorize",
                "token_endpoint": ISSUER + "token",
                "userinfo_endpoint": ISSUER + "userinfo",
                "jwks_uri": ISSUER + "jwks",
            }
        elif url == ISSUER + "token":
            on_token = claims.pop("_on_token", None)
            if callable(on_token):
                on_token()
            payload = {
                **claims,
                "iss": claims.get("iss", ISSUER),
                "aud": "pinaks-client",
                "iat": int(time.time()),
                "exp": int(time.time()) + 300,
            }
            data = {
                "access_token": "private-access-token",
                "refresh_token": "private-refresh-token",
                "token_type": "Bearer",
                "id_token": jwt.encode(
                    payload, "a fake signing key at least 32 bytes long", algorithm="HS256"
                ),
            }
        else:
            raise AssertionError(f"Unexpected provider request: {method} {url}")
        response._content = json.dumps(data).encode()
        return response

    monkeypatch.setattr(requests.Session, "request", request)
    with override_settings(SOCIALACCOUNT_PROVIDERS=OIDC):
        yield claims


def login(client: Client, *, process: str = "login") -> HttpResponseBase:
    start = client.post(f"/accounts/oidc/{PROVIDER}/login/", {"process": process})
    assert start.status_code == 302
    query = parse_qs(urlparse(start.headers["Location"]).query)
    assert query["response_type"] == ["code"]
    assert "code_challenge" in query
    return client.get(
        f"/accounts/oidc/{PROVIDER}/login/callback/",
        {"code": "fake-code", "state": query["state"][0]},
    )


def test_oidc_is_enabled_with_safe_defaults() -> None:
    assert "allauth.socialaccount" in settings.INSTALLED_APPS
    assert settings.SOCIALACCOUNT_STORE_TOKENS is False
    assert settings.SOCIALACCOUNT_EMAIL_AUTHENTICATION is False
    assert settings.SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT is False
    assert settings.SOCIALACCOUNT_LOGIN_ON_GET is False


def test_new_oidc_login_creates_read_only_local_session_and_no_tokens(
    provider: dict[str, object],
) -> None:

    client = Client()
    result = login(client)
    assert result.status_code == 302
    user = User.objects.get(pk=client.session["_auth_user_id"])
    assert user.role == UserRole.READ_ONLY
    assert not user.is_staff and not user.is_superuser and not user.has_usable_password()
    assert social_models.SocialAccount.objects.get(user=user).uid == "subject-1"
    assert not social_models.SocialToken.objects.exists()
    assert social_models.SocialAccount.objects.get(user=user).extra_data == {}
    assert AuditEvent.objects.filter(
        action_code="account.external_provisioned", target_identifier=str(user.pk)
    ).exists()
    assert AuditEvent.objects.filter(
        action_code="authentication.login_succeeded", metadata__authentication_method="oidc"
    ).exists()
    assert "private-access-token" not in json.dumps(dict(client.session))
    assert "private-refresh-token" not in json.dumps(dict(client.session))


def test_existing_identity_keeps_local_role_and_deactivation(provider: dict[str, object]) -> None:
    client = Client()
    login(client)
    user = User.objects.get(pk=client.session["_auth_user_id"])
    user.role = UserRole.COMPANY_MEMBER
    user.save()
    provider["email"] = "changed@example.test"
    second = Client()
    login(second)
    assert second.session["_auth_user_id"] == str(user.pk)
    user.refresh_from_db()
    assert user.role == UserRole.COMPANY_MEMBER
    user.is_active = False
    user.save()
    third = Client()
    login(third)
    assert "_auth_user_id" not in third.session


def test_matching_email_never_links_existing_local_user(provider: dict[str, object]) -> None:

    local = User.objects.create_user(
        username="local", email="oidc@example.test", password="local-password", role=UserRole.ADMIN
    )
    client = Client()
    login(client)
    assert "_auth_user_id" not in client.session
    assert not social_models.SocialAccount.objects.filter(user=local).exists()
    assert User.objects.count() == 1


def test_connect_is_explicit_and_identity_cannot_be_stolen(provider: dict[str, object]) -> None:

    local = User.objects.create_user(
        username="local", password="local-password", role=UserRole.ADMIN
    )
    client = Client()
    client.force_login(local)
    login(client, process="connect")
    account = social_models.SocialAccount.objects.get(user=local)
    assert account.uid == "subject-1"
    assert AuditEvent.objects.filter(action_code="account.connection_added", actor=local).exists()
    other = User.objects.create_user(username="other", password="other-password")
    client = Client()
    client.force_login(other)
    login(client, process="connect")
    account.refresh_from_db()
    assert account.user_id == local.pk
    with pytest.raises(IntegrityError), transaction.atomic():
        social_models.SocialAccount.objects.create(user=other, provider=PROVIDER, uid="subject-1")


def test_disconnect_requires_ownership_and_a_remaining_login_method(
    provider: dict[str, object],
) -> None:

    client = Client()
    login(client)
    user = User.objects.get(pk=client.session["_auth_user_id"])
    account = social_models.SocialAccount.objects.get(user=user)
    api = APIClient()
    api.force_authenticate(user)
    response = api.post(f"/api/v1/account/connections/{account.pk}/disconnect/", {}, format="json")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "last_login_method"
    user.set_password("local-password")
    user.save()
    other = User.objects.create_user(username="other")
    api.force_authenticate(other)
    assert (
        api.post(
            f"/api/v1/account/connections/{account.pk}/disconnect/", {}, format="json"
        ).status_code
        == 404
    )
    api.force_authenticate(user)
    assert (
        api.post(
            f"/api/v1/account/connections/{account.pk}/disconnect/", {}, format="json"
        ).status_code
        == 200
    )
    assert not social_models.SocialAccount.objects.filter(pk=account.pk).exists()
    assert AuditEvent.objects.filter(action_code="account.connection_removed", actor=user).exists()


def test_invalid_callback_state_never_logs_in(provider: dict[str, object]) -> None:
    client = Client()
    response = client.get(
        f"/accounts/oidc/{PROVIDER}/login/callback/", {"code": "fake", "state": "forged"}
    )
    assert response.status_code == 401
    assert "_auth_user_id" not in client.session
    assert not User.objects.exists()


def test_oidc_login_and_disconnect_require_csrf(provider: dict[str, object]) -> None:
    client = Client(enforce_csrf_checks=True)
    assert client.post(f"/accounts/oidc/{PROVIDER}/login/").status_code == 403
    assert client.get(f"/accounts/oidc/{PROVIDER}/login/").status_code == 200
    assert not User.objects.exists()


def test_unconfigured_provider_is_not_admitted() -> None:
    assert Client().post("/accounts/oidc/unconfigured/login/").status_code == 404


def test_rejected_provider_admission_is_audited_without_claims(provider: dict[str, object]) -> None:
    client = Client()
    start = client.post(f"/accounts/oidc/{PROVIDER}/login/")
    state = parse_qs(urlparse(start.headers["Location"]).query)["state"][0]
    response = client.get(
        f"/accounts/oidc/{PROVIDER}/login/callback/",
        {
            "error": "access_denied",
            "error_description": "sensitive provider message",
            "state": state,
        },
    )
    assert response.status_code == 302
    assert "_auth_user_id" not in client.session
    assert AuditEvent.objects.filter(
        action_code="authentication.login_failed", metadata__authentication_method="oidc"
    ).exists()
    assert "sensitive provider message" not in str(list(AuditEvent.objects.values("metadata")))


def test_invalid_issuer_never_logs_in(provider: dict[str, object]) -> None:
    provider["iss"] = "https://untrusted.example.test/"
    client = Client()
    login(client)
    assert "_auth_user_id" not in client.session
    assert not User.objects.exists()


def test_pending_signup_does_not_retain_oauth_tokens(provider: dict[str, object]) -> None:
    provider.pop("email")
    client = Client()
    login(client)
    assert "private-access-token" not in json.dumps(dict(client.session))
    assert "private-refresh-token" not in json.dumps(dict(client.session))


@pytest.mark.parametrize("deactivate", [False, True])
def test_connect_preserves_access_changes_during_provider_callback(
    provider: dict[str, object], deactivate: bool
) -> None:
    from pinaks.apps.accounts.services import update_user_access

    administrator = User.objects.create_user(username="administrator", role=UserRole.ADMIN)
    local = User.objects.create_user(
        username="local", password="local-password", role=UserRole.COMPANY_MEMBER
    )
    client = Client()
    client.force_login(local)

    def change_access() -> None:
        update_user_access(
            actor=administrator,
            user=User.objects.get(pk=local.pk),
            role=UserRole.READ_ONLY,
            is_active=not deactivate,
        )

    provider["_on_token"] = change_access
    login(client, process="connect")
    local.refresh_from_db()
    assert local.role == UserRole.READ_ONLY
    assert local.is_active is not deactivate
    assert social_models.SocialAccount.objects.filter(user=local).exists() is not deactivate
