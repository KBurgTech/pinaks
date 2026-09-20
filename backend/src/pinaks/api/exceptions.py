from collections.abc import Mapping
from typing import Any

from rest_framework.exceptions import APIException, ErrorDetail, NotAuthenticated, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler

_STATUS_ERROR_CODES = {
    400: "bad_request",
    401: "authentication_required",
    403: "permission_denied",
    404: "not_found",
    405: "method_not_allowed",
    406: "not_acceptable",
    415: "unsupported_media_type",
    429: "request_throttled",
}


class BusinessRuleViolation(APIException):
    """A domain/application rule prevented an otherwise valid request."""

    status_code = 409
    default_code = "business_rule_violation"
    default_detail = "The requested operation violates a business rule."

    def __init__(self, *, code: str, message: str) -> None:
        self.business_code = code
        super().__init__(detail=message, code=code)


def _serialize_error_detail(detail: object) -> object:
    if isinstance(detail, ErrorDetail):
        return {"code": detail.code, "message": str(detail)}
    if isinstance(detail, Mapping):
        return {str(key): _serialize_error_detail(value) for key, value in detail.items()}
    if isinstance(detail, (list, tuple)):
        return [_serialize_error_detail(value) for value in detail]
    return {"code": "invalid", "message": str(detail)}


def api_exception_handler(
    exception: Exception,
    # DRF defines this boundary as mixed framework-owned context values.
    context: dict[str, Any],
) -> Response | None:
    """Translate framework exceptions into the stable product error envelope."""
    response = exception_handler(exception, context)
    if response is None:
        return None

    if isinstance(exception, NotAuthenticated):
        response.data = {
            "error": {
                "code": "authentication_required",
                "message": str(exception.detail),
                "fields": {},
            }
        }
    elif isinstance(exception, BusinessRuleViolation):
        response.data = {
            "error": {
                "code": exception.business_code,
                "message": str(exception.detail),
                "fields": {},
            }
        }
    elif isinstance(exception, ValidationError):
        response.data = {
            "error": {
                "code": "validation_error",
                "message": "Request validation failed.",
                "fields": _serialize_error_detail(exception.detail),
            }
        }
    else:
        detail = response.data.get("detail") if isinstance(response.data, Mapping) else None
        message = str(detail) if detail is not None else "The request could not be completed."
        response.data = {
            "error": {
                "code": _STATUS_ERROR_CODES.get(response.status_code, "api_error"),
                "message": message,
                "fields": {},
            }
        }
    return response
