# Untyped allauth models are confined to this integration boundary.
import allauth.socialaccount.providers.openid_connect.views as oidc_views  # type: ignore[import-untyped]
from allauth.socialaccount.adapter import get_adapter  # type: ignore[import-untyped]
from allauth.socialaccount.models import SocialAccount  # type: ignore[import-untyped]
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpRequest, HttpResponseBase, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET

from pinaks.api.exceptions import BusinessRuleViolation
from pinaks.apps.accounts.models import User
from pinaks.apps.audit.services import record_event


def account_details(*, user: User, request: HttpRequest) -> dict[str, object]:
    return {
        "username": user.username,
        "has_password": user.has_usable_password(),
        "must_change_password": user.must_change_password,
        "connections": [
            {"id": account.pk, "provider": account.provider}
            for account in SocialAccount.objects.filter(user=user).order_by("pk")
        ],
        "providers": [
            {
                "id": app.provider_id,
                "name": app.name,
                "connect_url": reverse(
                    "openid_connect_login", kwargs={"provider_id": app.provider_id}
                ),
            }
            for app in get_adapter().list_apps(request, provider="openid_connect")
        ],
    }


@transaction.atomic
def disconnect_identity(*, user: User, connection_id: int) -> None:
    user = User.objects.select_for_update().get(pk=user.pk)
    account = get_object_or_404(SocialAccount, pk=connection_id, user=user)
    if (
        not user.has_usable_password()
        and not SocialAccount.objects.filter(user=user).exclude(pk=account.pk).exists()
    ):
        raise BusinessRuleViolation(
            code="last_login_method",
            message="Set a local password before removing your last connection.",
        )
    account.delete()
    record_event(
        actor=user,
        action_code="account.connection_removed",
        target_type="accounts.user",
        target_identifier=str(user.pk),
    )


@login_required
@require_GET
def connections_redirect(request: HttpRequest) -> HttpResponseRedirect:
    return HttpResponseRedirect("/app/account/")


@transaction.atomic
def oidc_callback(request: HttpRequest, provider_id: str) -> HttpResponseBase:
    # allauth owns protocol validation. The transaction lets the adapter lock the
    # canonical user after the network exchange and through connection persistence.
    response = oidc_views.callback(request, provider_id)
    assert isinstance(response, HttpResponseBase)
    return response
