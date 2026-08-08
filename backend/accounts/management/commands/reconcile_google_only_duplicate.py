from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import ExternalIdentity, User
from common.models import AuditLog
from wallets.circle import CircleClient, CircleError


CANONICAL_USER_ID = '7593262e-3352-40bd-b5d9-7bcb21d1a8d6'
DUPLICATE_USER_ID = 'c3b3278a-3bea-47e8-8950-ec49b1ed36d0'
CANONICAL_WALLET_PREFIX = '0x68301b'
CANONICAL_WALLET_SUFFIX = '7949'
DUPLICATE_WALLET_PREFIX = '0x63cc66'
DUPLICATE_WALLET_SUFFIX = '4c33'
CONFIRMATION = f'DELETE-EMPTY-DUPLICATE-{DUPLICATE_USER_ID}'


def _truncate(value):
    value = str(value or '')
    return value if len(value) <= 16 else f'{value[:8]}…{value[-4:]}'


def _matches_address(address, prefix, suffix):
    value = str(address or '').lower()
    return value.startswith(prefix.lower()) and value.endswith(suffix.lower())


def _meaningful_profile(profile, *, account_email=''):
    if profile is None:
        return False
    organisation = str(getattr(profile, 'organisation_name', '') or '').strip()
    github_username = str(getattr(profile, 'github_username', '') or '').strip()
    notification_email = str(getattr(profile, 'notification_email', '') or '').strip().lower()
    login_email = str(account_email or '').strip().lower()

    # The retired email flow initialized a CLIENT profile by copying the login
    # email and browser timezone. Those two values alone are bootstrap metadata,
    # not unique account activity. Custom contact, organisation, or GitHub data
    # remains meaningful and blocks deletion.
    custom_notification_email = bool(notification_email and notification_email != login_email)
    return bool(organisation or github_username or custom_notification_email)


class Command(BaseCommand):
    help = 'Remove the approved empty local EMAIL duplicate after Google-only reconciliation.'

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument('--dry-run', action='store_true')
        mode.add_argument('--apply', action='store_true')
        parser.add_argument('--canonical-user-id', required=True)
        parser.add_argument('--duplicate-user-id', required=True)
        parser.add_argument('--confirm', default='')

    def handle(self, *args, **options):
        if options['canonical_user_id'] != CANONICAL_USER_ID:
            raise CommandError('Canonical user ID does not match the approved account.')
        if options['duplicate_user_id'] != DUPLICATE_USER_ID:
            raise CommandError('Duplicate user ID does not match the approved account.')
        if options['apply'] and options['confirm'] != CONFIRMATION:
            raise CommandError('Exact duplicate-deletion confirmation is required.')
        if options['apply'] and not settings.VEYRA_RECONCILIATION_TESTS_PASSED:
            raise CommandError('Apply requires VEYRA_RECONCILIATION_TESTS_PASSED=true after validation.')

        report = self._inspect(lock=False)
        self._write_report(report)
        if report['blockers']:
            raise CommandError('Reconciliation blocked: ' + '; '.join(report['blockers']))
        if options['dry_run']:
            self.stdout.write(self.style.SUCCESS('DRY RUN PASSED — no database rows changed.'))
            return

        with transaction.atomic():
            report = self._inspect(lock=True)
            if report['blockers']:
                raise CommandError('Reconciliation blocked after lock: ' + '; '.join(report['blockers']))
            duplicate = report['duplicate']
            # Invalidate first, even though the approved local session rows are
            # subsequently removed with their local user.
            duplicate.veyra_sessions.select_for_update().update(revoked_at=report['checked_at'])
            for event in AuditLog.objects.select_for_update().filter(actor=duplicate):
                metadata = dict(event.metadata or {})
                metadata['removed_local_duplicate_user_id'] = DUPLICATE_USER_ID
                metadata['reconciliation'] = 'google_only_duplicate_removal'
                event.actor = None
                event.metadata = metadata
                event.save(update_fields=['actor', 'metadata'])

            # Delete only approved local rows, in an explicit reviewable order.
            # This command deliberately has no Circle deletion operation.
            duplicate.external_identities.all().delete()
            duplicate.capabilities.all().delete()
            if hasattr(duplicate, 'client_profile'):
                duplicate.client_profile.delete()
            if hasattr(duplicate, 'agent_owner_profile'):
                duplicate.agent_owner_profile.delete()
            duplicate.wallet_accounts.all().delete()
            duplicate.delete()
            if User.objects.filter(pk=DUPLICATE_USER_ID).exists():
                raise CommandError('Duplicate local user still exists after deletion.')
            canonical = User.objects.select_for_update().get(pk=CANONICAL_USER_ID)
            if set(canonical.capabilities.filter(revoked_at__isnull=True).values_list('code', flat=True)) != {
                'CLIENT', 'AGENT_OWNER'
            }:
                raise CommandError('Canonical capabilities changed during reconciliation.')
            wallet = canonical.wallet_accounts.get()
            if not _matches_address(wallet.address, CANONICAL_WALLET_PREFIX, CANONICAL_WALLET_SUFFIX):
                raise CommandError('Canonical wallet changed during reconciliation.')

        self.stdout.write(self.style.SUCCESS(
            'APPLY COMPLETE — approved local duplicate removed; external Circle EMAIL resources untouched.'
        ))

    @staticmethod
    def _backup_status():
        # An unset path must never look like a valid backup. Path('') resolves to
        # the current directory, whose stat() succeeds with a non-zero size, so
        # the configured value is checked before stat and the target is required
        # to be a regular file rather than a directory.
        configured = str(settings.VEYRA_RECONCILIATION_BACKUP_PATH or '').strip()
        if not configured:
            return Path(configured), 0, False
        backup = Path(configured)
        try:
            if not backup.is_file():
                return backup, 0, False
            size = backup.stat().st_size
        except OSError:
            return backup, 0, False
        return backup, size, size > 0

    def _inspect(self, *, lock):
        backup, backup_size, backup_ok = self._backup_status()
        users = User.objects.select_for_update() if lock else User.objects.all()
        try:
            canonical = users.get(pk=CANONICAL_USER_ID)
        except User.DoesNotExist as exc:
            raise CommandError('Canonical user is missing.') from exc
        duplicate = users.filter(pk=DUPLICATE_USER_ID).first()
        if duplicate is None:
            canonical_wallets = list(canonical.wallet_accounts.all())
            canonical_identity = canonical.external_identities.filter(
                provider=ExternalIdentity.Provider.CIRCLE_SSO_GOOGLE,
                method=ExternalIdentity.Method.GOOGLE,
            ).first()
            canonical_caps = set(canonical.capabilities.filter(
                revoked_at__isnull=True,
            ).values_list('code', flat=True))
            canonical_counts = self._related_counts(canonical)
            canonical_remote_ok, canonical_remote_error = self._confirm_canonical_remote(
                canonical_wallets,
                canonical_identity,
            )
            blockers = self._canonical_blockers(
                backup_ok=backup_ok,
                canonical_wallets=canonical_wallets,
                canonical_identity=canonical_identity,
                canonical_caps=canonical_caps,
                canonical_counts=canonical_counts,
                canonical_remote_ok=canonical_remote_ok,
                canonical_remote_error=canonical_remote_error,
            )
            return {
                'backup': backup, 'backup_size': backup_size, 'backup_ok': backup_ok,
                'canonical': canonical, 'duplicate': None, 'duplicate_absent': True,
                'canonical_wallets': canonical_wallets,
                'canonical_identity': canonical_identity,
                'canonical_caps': canonical_caps,
                'canonical_counts': canonical_counts,
                'canonical_remote_ok': canonical_remote_ok,
                'canonical_remote_error': canonical_remote_error,
                'retained_audit_logs': AuditLog.objects.filter(
                    metadata__removed_local_duplicate_user_id=DUPLICATE_USER_ID,
                ).count(),
                'blockers': blockers,
            }

        canonical_wallets = list(canonical.wallet_accounts.all())
        duplicate_wallets = list(duplicate.wallet_accounts.all())
        canonical_identity = canonical.external_identities.filter(
            provider=ExternalIdentity.Provider.CIRCLE_SSO_GOOGLE,
            method=ExternalIdentity.Method.GOOGLE,
        ).first()
        duplicate_identities = list(duplicate.external_identities.all())
        canonical_caps = set(canonical.capabilities.filter(revoked_at__isnull=True).values_list('code', flat=True))
        duplicate_caps = set(duplicate.capabilities.filter(revoked_at__isnull=True).values_list('code', flat=True))
        counts = self._related_counts(duplicate)
        canonical_counts = self._related_counts(canonical)

        canonical_remote_ok, canonical_remote_error = self._confirm_canonical_remote(
            canonical_wallets,
            canonical_identity,
        )

        live_balance = None
        balance_error = ''
        if len(duplicate_wallets) == 1:
            try:
                balances = CircleClient().wallet_balances_for_wallet(duplicate_wallets[0].circle_wallet_id)
                live_balance = sum((self._balance_value(item) for item in balances), Decimal('0'))
            except (CircleError, InvalidOperation, TypeError, ValueError) as exc:
                balance_error = str(exc)

        blockers = self._canonical_blockers(
            backup_ok=backup_ok,
            canonical_wallets=canonical_wallets,
            canonical_identity=canonical_identity,
            canonical_caps=canonical_caps,
            canonical_counts=canonical_counts,
            canonical_remote_ok=canonical_remote_ok,
            canonical_remote_error=canonical_remote_error,
        )
        if len(duplicate_wallets) != 1 or not _matches_address(
            duplicate_wallets[0].address if duplicate_wallets else '',
            DUPLICATE_WALLET_PREFIX, DUPLICATE_WALLET_SUFFIX,
        ):
            blockers.append('duplicate wallet does not match the approved empty wallet')
        if balance_error:
            blockers.append('duplicate live wallet balance could not be proven')
        elif live_balance != Decimal('0'):
            blockers.append('duplicate live wallet balance is non-zero')
        if counts['transactions']:
            blockers.append('duplicate has Circle transactions')
        if counts['payments']:
            blockers.append('duplicate has payments')
        for key in ('jobs', 'drafts', 'agents', 'karma', 'notifications', 'runner_devices', 'pairing_codes'):
            if counts[key]:
                blockers.append(f'duplicate has {key}')
        profile = getattr(duplicate, 'client_profile', None)
        if _meaningful_profile(profile, account_email=duplicate.email):
            blockers.append('duplicate profile contains meaningful data')
        if counts['profiles'] != 1 or profile is None or hasattr(duplicate, 'agent_owner_profile'):
            blockers.append('duplicate profile shape is not the approved single empty CLIENT profile')
        if duplicate_caps - canonical_caps:
            blockers.append('duplicate has a unique capability missing from canonical')
        if not duplicate_identities or any(item.method != ExternalIdentity.Method.EMAIL for item in duplicate_identities):
            blockers.append('duplicate does not have only EMAIL identities')

        return {
            'backup': backup, 'backup_size': backup_size, 'backup_ok': backup_ok,
            'canonical': canonical, 'duplicate': duplicate, 'duplicate_absent': False,
            'canonical_wallets': canonical_wallets, 'duplicate_wallets': duplicate_wallets,
            'canonical_identity': canonical_identity, 'duplicate_identities': duplicate_identities,
            'canonical_caps': canonical_caps, 'duplicate_caps': duplicate_caps,
            'counts': counts, 'canonical_counts': canonical_counts,
            'profile': profile, 'live_balance': live_balance,
            'canonical_remote_ok': canonical_remote_ok,
            'balance_error': balance_error, 'blockers': blockers,
            'checked_at': timezone.now(),
        }

    @staticmethod
    def _confirm_canonical_remote(canonical_wallets, canonical_identity):
        if len(canonical_wallets) != 1 or canonical_identity is None:
            return False, ''
        try:
            remote_wallet = CircleClient().get_wallet(canonical_wallets[0].circle_wallet_id)
            remote_user = CircleClient().get_user(remote_wallet.get('userId', ''))
            confirmed = (
                remote_wallet.get('id') == canonical_wallets[0].circle_wallet_id
                and remote_wallet.get('address', '').lower() == canonical_wallets[0].address.lower()
                and remote_wallet.get('userId') == canonical_identity.provider_user_id
                and remote_user.get('authMode') == 'SSO'
            )
            return confirmed, ''
        except (CircleError, TypeError, ValueError) as exc:
            return False, str(exc)

    @staticmethod
    def _canonical_blockers(
        *, backup_ok, canonical_wallets, canonical_identity, canonical_caps,
        canonical_counts, canonical_remote_ok, canonical_remote_error,
    ):
        blockers = []
        if not backup_ok:
            blockers.append('verified database backup is missing or empty')
        if canonical_identity is None:
            blockers.append('canonical Circle SSO Google identity migration is incomplete')
        if len(canonical_wallets) != 1 or not _matches_address(
            canonical_wallets[0].address if canonical_wallets else '',
            CANONICAL_WALLET_PREFIX, CANONICAL_WALLET_SUFFIX,
        ):
            blockers.append('canonical wallet does not match the approved wallet')
        if canonical_remote_error or not canonical_remote_ok:
            blockers.append('canonical Circle SSO user and wallet could not be confirmed live')
        if canonical_caps != {'CLIENT', 'AGENT_OWNER'}:
            blockers.append('canonical capabilities are not exactly CLIENT and AGENT_OWNER')
        canonical_minimums = {'jobs': 7, 'drafts': 12, 'agents': 4, 'transactions': 21}
        for key, minimum in canonical_minimums.items():
            if canonical_counts[key] < minimum:
                blockers.append(f'canonical known {key} history is incomplete')
        return blockers

    @staticmethod
    def _balance_value(item):
        return Decimal(str(item.get('amount', item.get('balance', '0')) or '0'))

    @staticmethod
    def _related_counts(user):
        WorkerAgent = apps.get_model('workers', 'WorkerAgent')
        WorkerReputationSnapshot = apps.get_model('workers', 'WorkerReputationSnapshot')
        return {
            'profiles': int(hasattr(user, 'client_profile')) + int(hasattr(user, 'agent_owner_profile')),
            'jobs': user.veyra_jobs.count(),
            'drafts': user.job_drafts.count(),
            'agents': WorkerAgent.objects.filter(owner_user=user).count(),
            'karma': WorkerReputationSnapshot.objects.filter(worker__owner_user=user).count(),
            'notifications': user.notifications.count(),
            'transactions': user.circle_transactions.count(),
            # No standalone Payment model exists; payment activity is represented
            # by CircleTransaction and funded jobs in this schema.
            'payments': 0,
            'sessions': user.veyra_sessions.count(),
            'audit_logs': AuditLog.objects.filter(actor=user).count(),
            'wallets': user.wallet_accounts.count(),
            'runner_devices': user.runner_devices.count(),
            'pairing_codes': user.runner_pairing_codes.count(),
        }

    def _write_report(self, report):
        self.stdout.write(f"Backup: {report['backup']} ({report['backup_size']} bytes; valid={report['backup_ok']})")
        canonical = report['canonical']
        self.stdout.write(f'Canonical user: {canonical.pk} created={canonical.date_joined.isoformat()}')
        if report.get('duplicate_absent'):
            self.stdout.write('Duplicate user: absent (already reconciled)')
            self.stdout.write(f"Canonical capabilities: {sorted(report['canonical_caps'])}")
            self.stdout.write('Canonical retained activity: ' + ', '.join(
                f'{key}={value}' for key, value in report['canonical_counts'].items()
            ))
            identity = report['canonical_identity']
            self.stdout.write('Canonical identity: ' + _truncate(
                identity.provider_user_id if identity else 'missing'
            ))
            self.stdout.write('Canonical wallets: ' + ', '.join(
                _truncate(item.address) for item in report['canonical_wallets']
            ))
            self.stdout.write(
                f"Canonical Circle SSO wallet confirmed live: {report['canonical_remote_ok']}"
            )
            self.stdout.write(
                f"Preserved duplicate audit logs: {report['retained_audit_logs']}"
            )
            self.stdout.write(
                'External Circle EMAIL user/wallet: retained untouched and inactive/orphaned in Veyra'
            )
            self.stdout.write('Safety gates: ' + ('PASS' if not report['blockers'] else 'BLOCKED'))
            for blocker in report['blockers']:
                self.stdout.write(self.style.ERROR(f'  - {blocker}'))
            return
        duplicate = report['duplicate']
        self.stdout.write(f'Duplicate user: {duplicate.pk} created={duplicate.date_joined.isoformat()}')
        self.stdout.write(f"Capabilities: canonical={sorted(report['canonical_caps'])} duplicate={sorted(report['duplicate_caps'])}")
        self.stdout.write('Authentication methods: canonical=GOOGLE/SSO duplicate=EMAIL')
        self.stdout.write(
            f"Profile present={report['profile'] is not None}; "
            f"meaningful={_meaningful_profile(report['profile'], account_email=duplicate.email)}"
        )
        self.stdout.write('Canonical retained activity: ' + ', '.join(f'{key}={value}' for key, value in report['canonical_counts'].items()))
        self.stdout.write('Activity: ' + ', '.join(f'{key}={value}' for key, value in report['counts'].items()))
        identity = report['canonical_identity']
        self.stdout.write('Canonical identity: ' + _truncate(identity.provider_user_id if identity else 'missing'))
        self.stdout.write('Duplicate identities: ' + ', '.join(_truncate(item.provider_user_id) for item in report['duplicate_identities']))
        self.stdout.write('Canonical wallets: ' + ', '.join(_truncate(item.address) for item in report['canonical_wallets']))
        self.stdout.write('Duplicate wallets: ' + ', '.join(_truncate(item.address) for item in report['duplicate_wallets']))
        self.stdout.write(f"Duplicate live aggregate token balance: {report['balance_error'] or report['live_balance']}")
        self.stdout.write(f"Canonical Circle SSO wallet confirmed live: {report['canonical_remote_ok']}")
        self.stdout.write('Cascade delete: identities, capabilities, profile, sessions, local wallet, local user')
        self.stdout.write('Retain: canonical user/profile/capabilities/history/wallet; audit logs with null actor + metadata')
        self.stdout.write('External Circle EMAIL user/wallet: retained untouched and inactive/orphaned in Veyra')
        self.stdout.write('Safety gates: ' + ('PASS' if not report['blockers'] else 'BLOCKED'))
        for blocker in report['blockers']:
            self.stdout.write(self.style.ERROR(f'  - {blocker}'))