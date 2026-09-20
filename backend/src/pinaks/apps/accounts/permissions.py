from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from pinaks.apps.accounts.capabilities import ROLE_CAPABILITIES
from pinaks.apps.accounts.models import User, UserRole


class RoleCapabilityPermission(BasePermission):
    capability: str

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        if not isinstance(user, User) or not user.is_authenticated or not user.is_active:
            return False
        capabilities = ROLE_CAPABILITIES[UserRole(user.role)]
        return bool(capabilities[self.capability])  # type: ignore[literal-required]


class CanRead(RoleCapabilityPermission):
    capability = "read"


class CanMutateDrafts(RoleCapabilityPermission):
    capability = "draft_mutation"


class CanIssueInvoices(RoleCapabilityPermission):
    capability = "invoice_issuance"


class CanManagePayments(RoleCapabilityPermission):
    capability = "payment_management"


class CanAdminister(RoleCapabilityPermission):
    capability = "administration"
