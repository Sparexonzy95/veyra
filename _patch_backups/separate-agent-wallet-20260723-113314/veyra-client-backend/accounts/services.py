import hashlib
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from common.models import AuditLog
from common.utils import digest_token, random_token
from accounts.models import ClientProfile, ExternalIdentity, PendingCircleAuth, User, UserCapability, VeyraSession


def _ua_hash(request) -> str:
    ua = request.headers.get('User-Agent', '')
    return hashlib.sha256(ua.encode()).hexdigest() if ua else ''


def issue_session(user: User, request):
    raw = random_token()
    session = VeyraSession.objects.create(
        user=user,
        token_hash=digest_token(raw),
        expires_at=timezone.now() + timedelta(seconds=settings.VEYRA_SESSION_TTL_SECONDS),
        user_agent_hash=_ua_hash(request),
    )
    User.objects.filter(pk=user.pk).update(last_login_at=timezone.now())
    return raw, session


def set_session_cookie(response, raw_token: str):
    response.set_cookie(
        settings.VEYRA_SESSION_COOKIE,
        raw_token,
        max_age=settings.VEYRA_SESSION_TTL_SECONDS,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite=settings.VEYRA_COOKIE_SAMESITE,
        path='/',
    )


def clear_auth_cookies(response):
    response.delete_cookie(settings.VEYRA_SESSION_COOKIE, path='/')
    response.delete_cookie(settings.VEYRA_ONBOARDING_COOKIE, path='/')


def create_pending_circle_auth(*, user_token: str, circle_user_id: str, method: str, email: str, display_name: str):
    raw = random_token()
    pending = PendingCircleAuth.objects.create(
        onboarding_token_hash=digest_token(raw),
        circle_user_token_hash=digest_token(user_token),
        circle_user_id=circle_user_id or '',
        auth_method=method,
        email_hint=email or '',
        display_name_hint=display_name or '',
        expires_at=timezone.now() + timedelta(seconds=settings.VEYRA_ONBOARDING_TTL_SECONDS),
    )
    return raw, pending


def get_pending_from_request(request, *, user_token: str | None = None):
    raw = request.COOKIES.get(settings.VEYRA_ONBOARDING_COOKIE)
    if not raw:
        return None
    pending = PendingCircleAuth.objects.filter(
        onboarding_token_hash=digest_token(raw),
        status=PendingCircleAuth.Status.ACTIVE,
        expires_at__gt=timezone.now(),
    ).first()
    if pending and user_token and pending.circle_user_token_hash != digest_token(user_token):
        return None
    return pending


def set_onboarding_cookie(response, raw_token: str):
    response.set_cookie(
        settings.VEYRA_ONBOARDING_COOKIE,
        raw_token,
        max_age=settings.VEYRA_ONBOARDING_TTL_SECONDS,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite=settings.VEYRA_COOKIE_SAMESITE,
        path='/',
    )


def grant_client(user: User, profile_data=None):
    capability, _ = UserCapability.objects.get_or_create(user=user, code=UserCapability.Code.CLIENT)
    if capability.revoked_at:
        capability.revoked_at = None
        capability.granted_at = timezone.now()
        capability.save(update_fields=['revoked_at', 'granted_at'])
    profile, _ = ClientProfile.objects.get_or_create(
        user=user,
        defaults={'notification_email': user.email, 'timezone': 'UTC'},
    )
    if profile_data:
        for field in ['organisation_name', 'notification_email', 'timezone', 'github_username']:
            if field in profile_data:
                setattr(profile, field, profile_data[field])
        profile.save()


def grant_agent_owner(user: User):
    capability, _ = UserCapability.objects.get_or_create(
        user=user,
        code=UserCapability.Code.AGENT_OWNER,
    )
    if capability.revoked_at:
        capability.revoked_at = None
        capability.granted_at = timezone.now()
        capability.save(update_fields=['revoked_at', 'granted_at'])


@transaction.atomic
def bind_identity_and_wallet_user(*, wallet, pending: PendingCircleAuth | None, circle_user_id: str, method: str, email: str, display_name: str):
    from wallets.models import WalletAccount

    existing_wallet = WalletAccount.objects.select_related('user').filter(circle_wallet_id=wallet['id']).first()
    if not existing_wallet:
        existing_wallet = WalletAccount.objects.select_related('user').filter(
            blockchain=wallet['blockchain'], address__iexact=wallet['address']
        ).first()

    if existing_wallet:
        user = existing_wallet.user
    else:
        user = User.objects.create_user(email=email or '', display_name=display_name or '')
        existing_wallet = WalletAccount.objects.create(
            user=user,
            circle_wallet_id=wallet['id'],
            wallet_set_id=wallet.get('walletSetId', '') or '',
            address=wallet['address'].lower(),
            blockchain=wallet['blockchain'],
            account_type=wallet.get('accountType', 'SCA'),
            custody_type='USER_CONTROLLED',
            status=wallet.get('state', 'LIVE'),
        )

    if email and not user.email:
        user.email = email
    if display_name and not user.display_name:
        user.display_name = display_name
    user.save(update_fields=['email', 'display_name'])

    # Circle social/email SDK userID is supplied by the browser and is not used as
    # an authority boundary. The verified Circle wallet ID is the stable identity.
    provider_id = f"wallet:{wallet['id']}"
    auth_method = method or (pending.auth_method if pending else ExternalIdentity.Method.GOOGLE)
    identity, created = ExternalIdentity.objects.get_or_create(
        provider=ExternalIdentity.Provider.CIRCLE,
        provider_user_id=provider_id,
        defaults={'user': user, 'method': auth_method},
    )
    if not created and identity.user_id != user.id:
        raise ValueError('Circle wallet identity is already bound to another Veyra account.')

    if pending and pending.requested_capability == UserCapability.Code.CLIENT:
        grant_client(user, pending.profile_data)
    if pending and pending.requested_capability == UserCapability.Code.AGENT_OWNER:
        grant_agent_owner(user)
    if pending:
        pending.status = PendingCircleAuth.Status.CONSUMED
        pending.consumed_at = timezone.now()
        pending.save(update_fields=['status', 'consumed_at'])

    AuditLog.objects.create(actor=user, action='CIRCLE_WALLET_BOUND', resource_type='WalletAccount', resource_id=str(existing_wallet.id))
    return user, existing_wallet
