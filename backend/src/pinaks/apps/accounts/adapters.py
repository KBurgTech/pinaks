# allauth does not publish typing information; dynamic provider objects stay at this boundary.
from allauth.account.adapter import DefaultAccountAdapter  # type: ignore[import-untyped]
from allauth.core.exceptions import ImmediateHttpResponse  # type: ignore[import-untyped]
from allauth.socialaccount import adapter as social_adapter  # type: ignore[import-untyped]
from allauth.socialaccount.models import SocialLogin  # type: ignore[import-untyped]
from django.contrib.auth.base_user import AbstractBaseUser
from django.db import transaction
from django.http import HttpRequest, HttpResponseForbidden

from pinaks.apps.accounts.models import User, UserRole
from pinaks.apps.audit.services import record_event


class AccountAdapter(DefaultAccountAdapter):
    """Keep local account creation under administrator control."""

    def is_open_for_signup(self, request: HttpRequest) -> bool:
        return False

    def set_password(self, user: AbstractBaseUser, password: str) -> None:
        if isinstance(user, User):
            user.must_change_password = False
        super().set_password(user, password)
        if isinstance(user, User):
            record_event(
                actor=user,
                action_code="account.password_changed",
                target_type="accounts.user",
                target_identifier=str(user.pk),
            )


class SocialAccountAdapter(social_adapter.DefaultSocialAccountAdapter):
    def populate_user(
        self, request: HttpRequest, sociallogin: SocialLogin, data: dict[str, str]
    ) -> User:
        user = super().populate_user(request, sociallogin, data)
        assert isinstance(user, User)
        # Retain only provider/subject; discard profile/group/token claims before lookup saves them.
        sociallogin.account.extra_data = {}
        return user

    def pre_social_login(self, request: HttpRequest, sociallogin: SocialLogin) -> None:
        sociallogin.token = None
        request._pinaks_authentication_method = "oidc"  # type: ignore[attr-defined]
        if sociallogin.state.get("process") == "connect":
            if not isinstance(request.user, User) or not request.user.is_authenticated:
                raise ImmediateHttpResponse(HttpResponseForbidden())
            # A provider round trip can outlive local access/password changes.
            # allauth saves the connecting user, so give it a fresh locked record.
            request.user = User.objects.select_for_update().get(pk=request.user.pk)
            if not request.user.is_active or request.user.must_change_password:
                raise ImmediateHttpResponse(HttpResponseForbidden())
        elif not sociallogin.is_existing:
            # Fail closed on collisions; linking always starts from an authenticated local session.
            user = sociallogin.user
            assert isinstance(user, User)
            if user.email and User.objects.filter(email__iexact=user.email).exists():
                raise ImmediateHttpResponse(HttpResponseForbidden())

    def is_open_for_signup(self, request: HttpRequest, sociallogin: SocialLogin) -> bool:
        # Only explicitly configured providers can reach this hook after a verified callback.
        return sociallogin.account.provider in {
            app.provider_id for app in self.list_apps(request, provider="openid_connect")
        }

    @transaction.atomic
    def save_user(
        self, request: HttpRequest, sociallogin: SocialLogin, form: object | None = None
    ) -> User:
        user = sociallogin.user
        assert isinstance(user, User)
        user.role = UserRole.READ_ONLY
        user.is_staff = False
        user.is_superuser = False
        user = super().save_user(request, sociallogin, form)
        assert isinstance(user, User)
        record_event(
            actor=user,
            action_code="account.external_provisioned",
            target_type="accounts.user",
            target_identifier=str(user.pk),
            request=request,
        )
        return user

    def get_connect_redirect_url(self, request: HttpRequest, socialaccount: object) -> str:
        return "/app/account/"

    def on_authentication_error(
        self,
        request: HttpRequest,
        provider: object,
        error: object = None,
        exception: object = None,
        extra_context: object = None,
    ) -> None:
        record_event(
            action_code="authentication.login_failed",
            target_type="accounts.user",
            request=request,
            metadata={"authentication_method": "oidc"},
        )
