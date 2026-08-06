import hashlib
from datetime import timedelta
from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone
from common.models import AuditLog
from common.utils import digest_token, random_token
from accounts.models import AgentOwnerProfile, ClientProfile, ExternalIdentity, PendingCircleAuth, User, UserCapability, VeyraSession


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
    from wallets.models import WalletAccount

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

    # A user-controlled Circle wallet becomes a client escrow wallet only when
    # the user explicitly enables the CLIENT workspace.
    WalletAccount.objects.filter(user=user).update(
        purpose=WalletAccount.Purpose.CLIENT_ESCROW,
    )


def grant_agent_owner(user: User, profile_data=None):
    from wallets.models import WalletAccount

    capability, _ = UserCapability.objects.get_or_create(
        user=user,
        code=UserCapability.Code.AGENT_OWNER,
    )
    if capability.revoked_at:
        capability.revoked_at = None
        capability.granted_at = timezone.now()
        capability.save(update_fields=['revoked_at', 'granted_at'])

    profile, _ = AgentOwnerProfile.objects.get_or_create(
        user=user,
        defaults={'notification_email': user.email, 'timezone': 'UTC'},
    )
    if profile_data:
        for field in ['notification_email', 'timezone']:
            if field in profile_data:
                setattr(profile, field, profile_data[field])
        profile.save()

    has_client_workspace = user.capabilities.filter(
        code=UserCapability.Code.CLIENT,
        revoked_at__isnull=True,
    ).exists()
    if not has_client_workspace:
        # This wallet may still anchor Circle sign-in for the account, but it is
        # never used to claim jobs, submit work, or receive agent payouts.
        WalletAccount.objects.filter(user=user).update(
            purpose=WalletAccount.Purpose.IDENTITY_ONLY,
        )


class CircleIdentityError(Exception):
    """A controlled, safe failure while resolving the Circle human identity.

    `code` is a stable machine-readable token for the client; the message is
    already safe to show to a signed-out visitor. Circle diagnostics never
    travel in either field.
    """

    def __init__(self, message: str, *, code: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def legacy_wallet_provider_id(circle_wallet_id: str) -> str:
    """The retired identity key: `wallet:<circle wallet id>`.

    Kept as a named helper so the migration, the runtime adoption path, and the
    tests all refer to exactly the same historic string.
    """
    return f'wallet:{circle_wallet_id}'


def resolve_circle_sso_user_id(wallet: dict) -> str:
    """Return the Circle end-user ID that owns `wallet`, verified server-side.

    The browser also reports a Circle `userId` through the Web SDK, but that
    value is client-supplied and must never decide which Veyra account a
    request unlocks. Circle's wallet resource, read with the developer API key,
    names its owning end user authoritatively, and the end user carries the
    immutable `authMode`. Google-only Veyra therefore accepts SSO users only.
    """
    from wallets.circle import CircleClient, CircleError

    wallet_id = wallet.get('id') or ''
    if not wallet_id:
        raise CircleIdentityError(
            'Your wallet could not be verified. Please try again.',
            code='circle_identity_unavailable',
            status_code=502,
        )

    try:
        remote_wallet = CircleClient().get_wallet(wallet_id)
        if (
            (remote_wallet or {}).get('id') != wallet_id
            or (remote_wallet or {}).get('address', '').lower() != wallet.get('address', '').lower()
        ):
            raise CircleIdentityError(
                'Your wallet could not be verified. Please try again.',
                code='circle_identity_unavailable',
                status_code=502,
            )
        circle_user_id = (remote_wallet or {}).get('userId') or ''
        if not circle_user_id:
            raise CircleIdentityError(
                'Your wallet could not be verified. Please try again.',
                code='circle_identity_unavailable',
                status_code=502,
            )
        circle_user = CircleClient().get_user(circle_user_id)
    except CircleError as exc:
        raise CircleIdentityError(
            'Your wallet could not be verified. Please try again.',
            code='circle_identity_unavailable',
            status_code=502,
        ) from exc

    auth_mode = (circle_user or {}).get('authMode') or ''
    if auth_mode != 'SSO':
        # An EMAIL (or PIN) Circle user is a different human identity owning a
        # different wallet. Binding one would create a second Veyra account.
        raise CircleIdentityError(
            'Email sign-in is not available. Continue with Google.',
            code='email_auth_disabled',
            status_code=403,
        )
    return circle_user_id


def resolve_google_wallet(wallets: list[dict]) -> tuple[str, dict] | tuple[None, None]:
    """Resolve the SSO human first, then select that human's persisted wallet.

    Circle may return several Arc wallets in any order.  An exact local wallet
    match therefore takes precedence over list order.  The selected wallet is
    still read back through Circle before its owner ID is trusted.
    """
    from wallets.models import WalletAccount
    from wallets.services import select_arc_wallet

    arc_wallets = [
        wallet for wallet in wallets
        if wallet.get('blockchain') == settings.ARC_BLOCKCHAIN
    ]
    if not arc_wallets:
        return None, None

    local_matches = []
    for candidate in arc_wallets:
        match = WalletAccount.objects.select_related('user').filter(
            circle_wallet_id=candidate.get('id', ''),
            address__iexact=candidate.get('address', ''),
            blockchain=settings.ARC_BLOCKCHAIN,
        ).first()
        if match:
            local_matches.append((match, candidate))
    if len({match.user_id for match, _candidate in local_matches}) > 1:
        raise CircleIdentityError(
            'Your wallet could not be verified. Please contact support.',
            code='wallet_binding_conflict',
            status_code=409,
        )

    candidate = local_matches[0][1] if local_matches else select_arc_wallet(arc_wallets)
    circle_sso_user_id = resolve_circle_sso_user_id(candidate)

    identity = ExternalIdentity.objects.select_related('user').filter(
        provider=ExternalIdentity.Provider.CIRCLE_SSO_GOOGLE,
        provider_user_id=circle_sso_user_id,
    ).first()
    if identity:
        canonical_wallet = WalletAccount.objects.filter(
            user=identity.user,
            blockchain=settings.ARC_BLOCKCHAIN,
        ).first()
        if canonical_wallet:
            for remote_wallet in arc_wallets:
                if (
                    remote_wallet.get('id') == canonical_wallet.circle_wallet_id
                    and remote_wallet.get('address', '').lower() == canonical_wallet.address.lower()
                ):
                    return circle_sso_user_id, remote_wallet

    return circle_sso_user_id, candidate


def _lock_circle_identity(circle_sso_user_id: str):
    """Serialise first-time callbacks for one SSO identity on PostgreSQL."""
    if connection.vendor != 'postgresql':
        return
    lock_value = int.from_bytes(
        hashlib.sha256(circle_sso_user_id.encode()).digest()[:8],
        byteorder='big',
        signed=True,
    )
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s)', [lock_value])


@transaction.atomic
def bind_google_identity_and_wallet(
    *,
    wallet,
    circle_sso_user_id: str,
    pending: PendingCircleAuth | None,
    email: str = '',
    display_name: str = '',
):
    """Resolve exactly one Veyra user for one Circle SSO (Google) end user.

    The human identity key is Circle's stable SSO user ID. A wallet is a
    resource that identity owns, so wallet lookup order, extra wallet
    resources, or a later wallet rotation can no longer fork the account.
    """
    from wallets.models import WalletAccount

    if not circle_sso_user_id:
        raise CircleIdentityError(
            'Your wallet could not be verified. Please try again.',
            code='circle_identity_unavailable',
            status_code=502,
        )

    _lock_circle_identity(circle_sso_user_id)

    # select_for_update serialises concurrent Google callbacks for the same
    # identity: the second one waits and then finds the row the first created.
    identity = (
        ExternalIdentity.objects.select_for_update()
        .select_related('user')
        .filter(
            provider=ExternalIdentity.Provider.CIRCLE_SSO_GOOGLE,
            provider_user_id=circle_sso_user_id,
        )
        .first()
    )
    user = identity.user if identity else None

    wallet_id = wallet['id']
    wallet_address = wallet['address'].lower()
    existing_wallet = WalletAccount.objects.select_related('user').filter(circle_wallet_id=wallet_id).first()
    if not existing_wallet:
        existing_wallet = WalletAccount.objects.select_related('user').filter(
            blockchain=wallet['blockchain'], address__iexact=wallet_address
        ).first()

    if user is None and existing_wallet:
        # First Google sign-in after this fix for an account that was created
        # under the old wallet-keyed identity. Adopt it rather than forking a
        # new user: the Circle SSO user demonstrably owns this wallet.
        user = existing_wallet.user
    elif user is not None and existing_wallet and existing_wallet.user_id != user.id:
        raise ValueError('Circle wallet is already linked to another Veyra account.')

    if user is not None:
        owned_wallet = WalletAccount.objects.select_for_update().filter(
            user=user, blockchain=wallet['blockchain']
        ).first()
        if owned_wallet and (
            owned_wallet.circle_wallet_id != wallet_id
            or owned_wallet.address.lower() != wallet_address
        ):
            # Never silently move a funded account onto a different wallet.
            raise CircleIdentityError(
                'This account is already linked to a different wallet. Sign in with the original Google account.',
                code='wallet_mismatch',
                status_code=409,
            )
        existing_wallet = owned_wallet or existing_wallet

    requested_capability = pending.requested_capability if pending else ''
    wallet_purpose = (
        WalletAccount.Purpose.IDENTITY_ONLY
        if requested_capability == UserCapability.Code.AGENT_OWNER
        else WalletAccount.Purpose.CLIENT_ESCROW
    )

    if user is None:
        user = User.objects.create_user(email=email or '', display_name=display_name or '')
    if existing_wallet:
        if requested_capability == UserCapability.Code.CLIENT:
            existing_wallet.purpose = WalletAccount.Purpose.CLIENT_ESCROW
            existing_wallet.save(update_fields=['purpose', 'updated_at'])
    else:
        existing_wallet = WalletAccount.objects.create(
            user=user,
            circle_wallet_id=wallet_id,
            wallet_set_id=wallet.get('walletSetId', '') or '',
            address=wallet_address,
            blockchain=wallet['blockchain'],
            account_type=wallet.get('accountType', 'SCA'),
            custody_type='USER_CONTROLLED',
            purpose=wallet_purpose,
            status=wallet.get('state', 'LIVE'),
        )

    if email and not user.email:
        user.email = email
    if display_name and not user.display_name:
        user.display_name = display_name
    user.save(update_fields=['email', 'display_name'])

    if identity is None:
        identity, _ = ExternalIdentity.objects.get_or_create(
            provider=ExternalIdentity.Provider.CIRCLE_SSO_GOOGLE,
            provider_user_id=circle_sso_user_id,
            defaults={'user': user, 'method': ExternalIdentity.Method.GOOGLE},
        )
    if identity.user_id != user.id:
        raise ValueError('This Google identity is already bound to another Veyra account.')

    # Retire the wallet-keyed row only now that the stable identity exists.
    ExternalIdentity.objects.filter(
        user=user,
        provider=ExternalIdentity.Provider.CIRCLE,
        provider_user_id=legacy_wallet_provider_id(existing_wallet.circle_wallet_id),
    ).delete()

    if pending and pending.requested_capability == UserCapability.Code.CLIENT:
        grant_client(user, pending.profile_data)
    if pending and pending.requested_capability == UserCapability.Code.AGENT_OWNER:
        grant_agent_owner(user, pending.profile_data)
    if pending:
        pending.status = PendingCircleAuth.Status.CONSUMED
        pending.consumed_at = timezone.now()
        pending.save(update_fields=['status', 'consumed_at'])

    AuditLog.objects.create(actor=user, action='CIRCLE_WALLET_BOUND', resource_type='WalletAccount', resource_id=str(existing_wallet.id))
    return user, existing_wallet
