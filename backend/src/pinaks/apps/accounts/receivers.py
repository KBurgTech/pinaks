from allauth.socialaccount.signals import (  # type: ignore[import-untyped]
    social_account_added,
    social_account_removed,
)
from django.dispatch import receiver
from django.http import HttpRequest

from pinaks.apps.accounts.models import User
from pinaks.apps.audit.services import record_event


@receiver(social_account_added, dispatch_uid="account_connection_added")
def record_connection_added(sender: object, request: HttpRequest, **kwargs: object) -> None:
    assert isinstance(request.user, User)
    record_event(
        actor=request.user,
        action_code="account.connection_added",
        target_type="accounts.user",
        target_identifier=str(request.user.pk),
        request=request,
    )


@receiver(social_account_removed, dispatch_uid="account_connection_removed")
def record_connection_removed(sender: object, request: HttpRequest, **kwargs: object) -> None:
    assert isinstance(request.user, User)
    record_event(
        actor=request.user,
        action_code="account.connection_removed",
        target_type="accounts.user",
        target_identifier=str(request.user.pk),
        request=request,
    )
