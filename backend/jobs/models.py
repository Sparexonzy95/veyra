import uuid
from django.conf import settings
from django.db import models
from common.models import TimeStampedModel



class GitHubAppInstallation(TimeStampedModel):
    class Status(models.TextChoices):
        CONNECTED = "CONNECTED", "Connected"
        CHECKING = "CHECKING", "Checking"
        LIMITED_ACCESS = "LIMITED_ACCESS", "Limited access"
        CREDENTIAL_GENERATION_FAILED = "CREDENTIAL_GENERATION_FAILED", "Credential generation failed"
        SUSPENDED = "SUSPENDED", "Suspended"
        RECONNECT_REQUIRED = "RECONNECT_REQUIRED", "Reconnect required"
        DISCONNECTED = "DISCONNECTED", "Disconnected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="github_app_installations",
        on_delete=models.CASCADE,
    )
    installation_id = models.PositiveBigIntegerField(unique=True)
    account_id = models.PositiveBigIntegerField(default=0)
    account_login = models.CharField(max_length=160)
    account_type = models.CharField(max_length=32, blank=True)
    repository_selection = models.CharField(max_length=32, default="selected")
    permissions = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=40,
        choices=Status.choices,
        default=Status.CHECKING,
    )
    suspended_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["account_login"]
        indexes = [
            models.Index(fields=["client", "status"], name="jobs_github_client__b41410_idx"),
            models.Index(fields=["installation_id"], name="jobs_github_install_6c1057_idx"),
        ]


class GitHubRepositoryAccess(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    installation = models.ForeignKey(
        GitHubAppInstallation,
        related_name="repositories",
        on_delete=models.CASCADE,
    )
    github_repository_id = models.PositiveBigIntegerField(unique=True)
    owner = models.CharField(max_length=160)
    name = models.CharField(max_length=160)
    full_name = models.CharField(max_length=321)
    private = models.BooleanField(default=False)
    default_branch = models.CharField(max_length=160, default="main")
    html_url = models.URLField(blank=True)
    permissions = models.JSONField(default=dict, blank=True)
    active = models.BooleanField(default=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["full_name"]
        indexes = [
            models.Index(fields=["installation", "active"], name="jobs_github_install_977b4b_idx"),
            models.Index(fields=["owner", "name"], name="jobs_github_owner_5d0bea_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["installation", "full_name"],
                name="uniq_github_installation_repository",
            )
        ]


class JobDraft(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        READY = 'READY', 'Ready for review'
        LOCKED = 'LOCKED', 'Locked for funding'
        FUNDING = 'FUNDING', 'Funding'
        FUNDED = 'FUNDED', 'Funded'
        ARCHIVED = 'ARCHIVED', 'Archived'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='job_drafts', on_delete=models.CASCADE)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    github_issue_url = models.URLField()
    github_repository_access = models.ForeignKey(
        GitHubRepositoryAccess,
        related_name="job_drafts",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    repository_owner = models.CharField(max_length=120)
    repository_name = models.CharField(max_length=120)
    target_branch = models.CharField(max_length=120, default='main')
    issue_number = models.PositiveBigIntegerField()
    issue_title = models.CharField(max_length=240)
    issue_body = models.TextField(blank=True)
    budget_usdc = models.DecimalField(max_digits=30, decimal_places=6)
    deadline = models.DateTimeField()
    acceptance_criteria = models.JSONField(default=list)
    advanced_options = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['client', 'status'])]

class JobFundingSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    draft = models.OneToOneField(JobDraft, related_name='funding_snapshot', on_delete=models.PROTECT)
    repository_commitment = models.JSONField()
    task_commitment = models.JSONField()
    policy_commitment = models.JSONField()
    repository_hash = models.CharField(max_length=66)
    task_hash = models.CharField(max_length=66)
    policy_hash = models.CharField(max_length=66)
    budget_atomic = models.DecimalField(max_digits=40, decimal_places=0)
    expires_at = models.PositiveBigIntegerField()
    verifier_address = models.CharField(max_length=42)
    invited_provider_address = models.CharField(max_length=42)
    locked_at = models.DateTimeField(auto_now_add=True)

class VeyraJob(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='veyra_jobs', on_delete=models.CASCADE)
    draft = models.OneToOneField(JobDraft, related_name='job', on_delete=models.PROTECT)
    onchain_job_id = models.PositiveBigIntegerField(unique=True)
    status = models.CharField(max_length=24)
    client_status = models.CharField(max_length=32)
    client_address = models.CharField(max_length=42)
    invited_provider_address = models.CharField(max_length=42)
    provider_address = models.CharField(max_length=42, blank=True)
    verifier_address = models.CharField(max_length=42)
    budget_atomic = models.DecimalField(max_digits=40, decimal_places=0)
    expires_at = models.PositiveBigIntegerField()
    claim_deadline = models.PositiveBigIntegerField(default=0)
    repository_hash = models.CharField(max_length=66)
    task_hash = models.CharField(max_length=66)
    policy_hash = models.CharField(max_length=66)
    deliverable_hash = models.CharField(max_length=66, blank=True)
    commit_hash = models.CharField(max_length=66, blank=True)
    pull_request_number = models.PositiveBigIntegerField(default=0)
    report_hash = models.CharField(max_length=66, blank=True)
    evidence_hash = models.CharField(max_length=66, blank=True)
    rejection_reason_hash = models.CharField(max_length=66, blank=True)
    creation_tx_hash = models.CharField(max_length=66, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['client', 'client_status'])]

class ArcEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    chain_id = models.PositiveBigIntegerField()
    contract_address = models.CharField(max_length=42)
    transaction_hash = models.CharField(max_length=66)
    log_index = models.PositiveIntegerField()
    block_number = models.PositiveBigIntegerField()
    event_name = models.CharField(max_length=80)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['chain_id', 'contract_address', 'transaction_hash', 'log_index'], name='uniq_arc_event'),
        ]
        ordering = ['block_number', 'log_index']

class Notification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='notifications', on_delete=models.CASCADE)
    event_type = models.CharField(max_length=80)
    title = models.CharField(max_length=160)
    body = models.TextField(blank=True)
    resource_type = models.CharField(max_length=80, blank=True)
    resource_id = models.CharField(max_length=120, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
