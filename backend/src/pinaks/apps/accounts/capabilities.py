from typing import Final, TypedDict

from pinaks.apps.accounts.models import UserRole


class CapabilityValues(TypedDict):
    read: bool
    draft_mutation: bool
    invoice_issuance: bool
    payment_management: bool
    administration: bool


ROLE_CAPABILITIES: Final[dict[UserRole, CapabilityValues]] = {
    UserRole.ADMIN: {
        "read": True,
        "draft_mutation": True,
        "invoice_issuance": True,
        "payment_management": True,
        "administration": True,
    },
    UserRole.COMPANY_MEMBER: {
        "read": True,
        "draft_mutation": True,
        "invoice_issuance": True,
        "payment_management": True,
        "administration": False,
    },
    UserRole.READ_ONLY: {
        "read": True,
        "draft_mutation": False,
        "invoice_issuance": False,
        "payment_management": False,
        "administration": False,
    },
}
