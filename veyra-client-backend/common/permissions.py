from rest_framework.permissions import BasePermission

class HasClientCapability(BasePermission):
    message = 'Client capability is required.'

    def has_permission(self, request, view):
        user = getattr(request, 'user', None)
        return bool(user and user.is_authenticated and user.capabilities.filter(code='CLIENT', revoked_at__isnull=True).exists())


class HasAgentOwnerCapability(BasePermission):
    message = 'Agent owner capability is required.'

    def has_permission(self, request, view):
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return False
        if user.is_staff or user.is_superuser:
            return True
        return user.capabilities.filter(
            code='AGENT_OWNER',
            revoked_at__isnull=True,
        ).exists()
