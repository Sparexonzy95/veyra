from django.conf import settings
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from common.utils import digest_token
from accounts.models import VeyraSession

class VeyraSessionAuthentication(BaseAuthentication):
    def authenticate(self, request):
        raw = request.COOKIES.get(settings.VEYRA_SESSION_COOKIE)
        if not raw:
            return None
        token_hash = digest_token(raw)
        try:
            session = VeyraSession.objects.select_related('user').get(token_hash=token_hash, revoked_at__isnull=True)
        except VeyraSession.DoesNotExist as exc:
            raise AuthenticationFailed('Session is invalid.') from exc
        if session.expires_at <= timezone.now():
            raise AuthenticationFailed('Session has expired.')
        if not session.user.is_active or session.user.status != 'ACTIVE':
            raise AuthenticationFailed('User account is unavailable.')
        VeyraSession.objects.filter(pk=session.pk).update(last_used_at=timezone.now())
        request.veyra_session = session
        return session.user, session
