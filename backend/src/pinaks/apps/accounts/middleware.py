from collections.abc import Callable

from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse

from pinaks.apps.accounts.models import User


class RequirePasswordChangeMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if isinstance(request.user, User) and request.user.must_change_password:
            allowed = (
                "/api/v1/account/",
                "/api/v1/account/password/",
                "/api/v1/capabilities/",
                "/app/account/",
                "/accounts/logout/",
            )
            if request.path not in allowed and not request.path.startswith(
                ("/static/", "/app/assets/")
            ):
                if request.path.startswith("/api/"):
                    return JsonResponse(
                        {
                            "error": {
                                "code": "password_change_required",
                                "message": "Change your temporary password before continuing.",
                                "fields": {},
                            }
                        },
                        status=403,
                    )
                return HttpResponseRedirect("/app/account/")
        return self.get_response(request)
