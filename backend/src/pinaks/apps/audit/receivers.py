from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver
from django.http import HttpRequest

from pinaks.apps.accounts.models import User
from pinaks.apps.audit.services import record_event


@receiver(user_logged_in, dispatch_uid="audit_successful_login")
def record_successful_login(
    sender: object,
    request: HttpRequest,
    user: User,
    **kwargs: object,
) -> None:
    del sender, kwargs
    record_event(
        actor=user,
        action_code="authentication.login_succeeded",
        target_type="accounts.user",
        target_identifier=str(user.pk),
        request=request,
        metadata={"authentication_method": "local"},
    )


@receiver(user_login_failed, dispatch_uid="audit_failed_login")
def record_failed_login(
    sender: object,
    credentials: dict[str, object],
    request: HttpRequest | None,
    **kwargs: object,
) -> None:
    del sender, credentials, kwargs
    record_event(
        action_code="authentication.login_failed",
        target_type="accounts.user",
        request=request,
        metadata={"authentication_method": "local"},
    )
