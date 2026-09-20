from allauth.account.adapter import DefaultAccountAdapter  # type: ignore[import-untyped]
from django.http import HttpRequest


class AccountAdapter(DefaultAccountAdapter):
    """Keep local account creation under administrator control."""

    def is_open_for_signup(self, request: HttpRequest) -> bool:
        return False
