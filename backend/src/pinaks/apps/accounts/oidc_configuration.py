import hashlib
from collections.abc import Mapping
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured


def oidc_configuration(
    environment: Mapping[str, str],
) -> dict[str, dict[str, list[dict[str, object]]]]:
    issuer = environment.get("OIDC_ISSUER", "")
    client_id = environment.get("OIDC_CLIENT_ID", "")
    secret = environment.get("OIDC_CLIENT_SECRET", "")
    if not any((issuer, client_id, secret)):
        return {"openid_connect": {"APPS": []}}
    parsed = urlsplit(issuer)
    if (
        not all((issuer, client_id, secret))
        or parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ImproperlyConfigured(
            "OIDC requires an HTTPS issuer, client ID and deployment client secret."
        )
    return {
        "openid_connect": {
            "APPS": [
                {
                    # Changing issuers cannot reuse identities from a previous provider.
                    "provider_id": "oidc-" + hashlib.sha256(issuer.encode()).hexdigest(),
                    "name": environment.get("OIDC_NAME", "Authentik"),
                    "client_id": client_id,
                    "secret": secret,
                    "settings": {
                        "server_url": issuer,
                        "fetch_userinfo": False,
                        "oauth_pkce_enabled": True,
                    },
                }
            ],
        },
    }
