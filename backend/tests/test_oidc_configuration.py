import pytest
from django.core.exceptions import ImproperlyConfigured

from pinaks.apps.accounts.oidc_configuration import oidc_configuration


def test_oidc_disabled_until_configured_and_provider_identity_is_issuer_bound() -> None:
    assert oidc_configuration({}) == {"openid_connect": {"APPS": []}}
    environment = {
        "OIDC_ISSUER": "https://identity.example.test/pinaks/",
        "OIDC_CLIENT_ID": "pinaks",
        "OIDC_CLIENT_SECRET": "deployment-only-secret",
    }
    configured = oidc_configuration(environment)["openid_connect"]["APPS"][0]
    assert configured["settings"] == {
        "server_url": environment["OIDC_ISSUER"],
        "fetch_userinfo": False,
        "oauth_pkce_enabled": True,
    }
    changed = oidc_configuration(
        {**environment, "OIDC_ISSUER": "https://other.example.test/pinaks/"}
    )["openid_connect"]["APPS"][0]
    assert configured["provider_id"] != changed["provider_id"]
    assert "deployment-only-secret" not in str(configured["provider_id"])


@pytest.mark.parametrize(
    "environment",
    [
        {"OIDC_CLIENT_ID": "pinaks"},
        {"OIDC_ISSUER": "https://identity.example.test/"},
        {
            "OIDC_ISSUER": "http://identity.example.test/",
            "OIDC_CLIENT_ID": "pinaks",
            "OIDC_CLIENT_SECRET": "secret",
        },
        {
            "OIDC_ISSUER": "https://user:secret@identity.example.test/",
            "OIDC_CLIENT_ID": "pinaks",
            "OIDC_CLIENT_SECRET": "secret",
        },
    ],
)
def test_incomplete_or_unsafe_oidc_configuration_fails_closed(environment: dict[str, str]) -> None:
    with pytest.raises(ImproperlyConfigured):
        oidc_configuration(environment)
