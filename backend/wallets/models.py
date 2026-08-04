import uuid
from django.conf import settings
from django.db import models
from common.models import TimeStampedModel


class WalletAccount(TimeStampedModel):
    class Purpose(models.TextChoices):
        IDENTITY_ONLY = 'IDENTITY_ONLY', 'Sign-in identity only'
        CLIENT_ESCROW = 'CLIENT_ESCROW', 'Client escrow wallet'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='wallet_accounts', on_delete=models.CASCADE)
    circle_wallet_id = models.CharField(max_length=64, unique=True)
    wallet_set_id = models.CharField(max_length=64, blank=True)
    address = models.CharField(max_length=42)
    blockchain = models.CharField(max_length=40)
    account_type = models.CharField(max_length=16, default='SCA')
    custody_type = models.CharField(max_length=32, default='USER_CONTROLLED')
    purpose = models.CharField(
        max_length=24,
        choices=Purpose.choices,
        default=Purpose.CLIENT_ESCROW,
    )
    status = models.CharField(max_length=24, default='LIVE')
    last_usdc_balance = models.DecimalField(max_digits=30, decimal_places=6, default=0)
    last_balance_sync_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'blockchain'], name='uniq_user_blockchain_wallet'),
            models.UniqueConstraint(fields=['blockchain', 'address'], name='uniq_blockchain_wallet_address'),
        ]
        indexes = [models.Index(fields=['address']), models.Index(fields=['blockchain', 'status'])]

    def save(self, *args, **kwargs):
        self.address = self.address.lower()
        super().save(*args, **kwargs)


class CircleTransaction(TimeStampedModel):
    class Purpose(models.TextChoices):
        WALLET_CREATE = 'WALLET_CREATE', 'Wallet create'
        USDC_APPROVAL = 'USDC_APPROVAL', 'USDC approval'
        JOB_CREATE = 'JOB_CREATE', 'Job create'
        JOB_CANCEL = 'JOB_CANCEL', 'Job cancel'
        JOB_REFUND = 'JOB_REFUND', 'Job refund'

    class Status(models.TextChoices):
        CREATED = 'CREATED', 'Created'
        CHALLENGE_READY = 'CHALLENGE_READY', 'Challenge ready'
        USER_APPROVAL_PENDING = 'USER_APPROVAL_PENDING', 'User approval pending'
        SUBMITTED = 'SUBMITTED', 'Submitted'
        PENDING_ONCHAIN = 'PENDING_ONCHAIN', 'Pending onchain'
        CONFIRMED = 'CONFIRMED', 'Confirmed'
        DENIED = 'DENIED', 'Denied'
        FAILED = 'FAILED', 'Failed'
        EXPIRED = 'EXPIRED', 'Expired'
        EVENT_MISMATCH = 'EVENT_MISMATCH', 'Event mismatch'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='circle_transactions', on_delete=models.CASCADE)
    wallet = models.ForeignKey(WalletAccount, related_name='transactions', on_delete=models.PROTECT)
    draft = models.ForeignKey(
        'jobs.JobDraft', related_name='transactions', on_delete=models.PROTECT,
        null=True, blank=True,
    )
    job = models.ForeignKey(
        'jobs.VeyraJob', related_name='transactions', on_delete=models.PROTECT,
        null=True, blank=True,
    )
    purpose = models.CharField(max_length=32, choices=Purpose.choices)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.CREATED)
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True)
    circle_challenge_id = models.CharField(max_length=128, blank=True)
    circle_transaction_id = models.CharField(max_length=128, blank=True, unique=True, null=True)
    circle_reference_id = models.CharField(max_length=128, blank=True)
    arc_transaction_hash = models.CharField(max_length=66, blank=True)
    contract_address = models.CharField(max_length=42, blank=True)
    call_data_hash = models.CharField(max_length=66, blank=True)
    request_metadata = models.JSONField(default=dict, blank=True)
    event_payload = models.JSONField(default=dict, blank=True)
    block_number = models.PositiveBigIntegerField(null=True, blank=True)
    gas_used = models.PositiveBigIntegerField(null=True, blank=True)
    receipt_status = models.PositiveSmallIntegerField(null=True, blank=True)
    sync_attempts = models.PositiveIntegerField(default=0)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    failure_code = models.CharField(max_length=80, blank=True)
    failure_message = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['circle_challenge_id']),
            models.Index(fields=['arc_transaction_hash']),
            models.Index(fields=['draft', 'purpose', 'status']),
        ]
