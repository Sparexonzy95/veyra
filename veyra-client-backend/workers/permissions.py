from rest_framework.permissions import BasePermission

from common.permissions import HasAgentOwnerCapability


class IsVeyraAdmin(BasePermission):
    message = "Veyra administrator access is required."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        if user.is_staff or user.is_superuser:
            return True
        return user.capabilities.filter(code="ADMIN", revoked_at__isnull=True).exists()


class IsAgentOwner(HasAgentOwnerCapability):
    """Backward-compatible name for the Agent Owner workspace permission."""
