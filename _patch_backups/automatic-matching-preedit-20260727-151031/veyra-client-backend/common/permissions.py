from rest_framework.permissions import BasePermission

class HasClientCapability(BasePermission):
    message = 'Client capability is required.'

    def has_permission(self, request, view):
        user = getattr(request, 'user', None)
        return bool(user and user.is_authenticated and user.capabilities.filter(code='CLIENT', revoked_at__isnull=True).exists())
