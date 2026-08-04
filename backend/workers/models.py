import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from common.models import TimeStampedModel


evm_address_validator = RegexValidator(
    regex=r"^0x[a-fA-F0-9]{40}$",
    message="Enter a valid EVM wallet address.",
)


class WorkerAgent(TimeStampedModel):
    """A Veyra worker identity.

    This model stores public configuration and onboarding state only. Circle
    entity secrets, Circle API keys, GitHub tokens, and coding-engine secrets
    must remain in the runtime secret store and are deliberately not modelled.
    """

    class OwnerType(models.TextChoices):
        VEYRA = "VEYRA", "Veyra"
        EXTERNAL = "EXTERNAL", "External owner"

    class AgentRole(models.TextChoices):
        WORKER = "WORKER", "Worker agent"
        VERIFIER = "VERIFIER", "Verifier agent"

    class Status(models.TextChoices):
        SETUP_REQUIRED = "SETUP_REQUIRED", "Setup required"
        PROFILE_READY = "PROFILE_READY", "Profile ready"
        PROVISIONING = "PROVISIONING", "Provisioning"
        RUNTIME_CONNECTED = "RUNTIME_CONNECTED", "Runtime connected"
        READY_FOR_QUALIFICATION = "READY_FOR_QUALIFICATION", "Ready for qualification"
        RUNTIME_VERIFICATION_FAILED = "RUNTIME_VERIFICATION_FAILED", "Runtime verification failed"
        WALLET_CREATION_FAILED = "WALLET_CREATION_FAILED", "Wallet creation failed"
        CONTRACT_AUTHORISATION_FAILED = "CONTRACT_AUTHORISATION_FAILED", "Contract authorisation failed"
        PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE", "Provider unavailable"
        CONNECTION_FAILED = "CONNECTION_FAILED", "Connection failed"
        ENGINE_CONNECTED = "ENGINE_CONNECTED", "Engine connected"
        WALLET_READY = "WALLET_READY", "Wallet ready"
        PAYOUT_READY = "PAYOUT_READY", "Payout wallet ready"
        GITHUB_READY = "GITHUB_READY", "GitHub ready"
        AUTHORISATION_PENDING = "AUTHORISATION_PENDING", "Authorisation pending"
        TESTING = "TESTING", "Test assignment running"
        ACTIVE = "ACTIVE", "Active"
        PAUSED = "PAUSED", "Paused"
        SUSPENDED = "SUSPENDED", "Suspended"

    class RepositoryStrategy(models.TextChoices):
        FORK_PR = "FORK_PR", "Fork and pull request"

    class EngineProvider(models.TextChoices):
        OPENCODE = "OPENCODE", "OpenCode"
        CUSTOM = "CUSTOM", "Custom worker runtime"

    class Specialisation(models.TextChoices):
        PYTHON_BACKEND = "PYTHON_BACKEND", "Python backend agent"
        JAVASCRIPT_FRONTEND = "JAVASCRIPT_FRONTEND", "JavaScript frontend agent"
        FULL_STACK_WEB = "FULL_STACK_WEB", "Full-stack web agent"
        SMART_CONTRACT = "SMART_CONTRACT", "Smart contract agent"
        TESTING_QA = "TESTING_QA", "Testing and QA agent"
        DOCUMENTATION = "DOCUMENTATION", "Documentation agent"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)

    owner_type = models.CharField(
        max_length=16,
        choices=OwnerType.choices,
        default=OwnerType.VEYRA,
    )
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="worker_agents",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    agent_role = models.CharField(
        max_length=16,
        choices=AgentRole.choices,
        default=AgentRole.WORKER,
    )

    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.SETUP_REQUIRED,
    )
    avatar_url = models.URLField(blank=True)
    specialisation = models.CharField(
        max_length=32,
        choices=Specialisation.choices,
        default=Specialisation.PYTHON_BACKEND,
    )
    languages = models.JSONField(default=list, blank=True)
    frameworks = models.JSONField(default=list, blank=True)
    testing_tools = models.JSONField(default=list, blank=True)
    task_types = models.JSONField(default=list, blank=True)
    skills = models.JSONField(default=list)

    minimum_budget_usdc = models.DecimalField(
        max_digits=30,
        decimal_places=6,
        default="1.000000",
    )
    maximum_budget_usdc = models.DecimalField(
        max_digits=30,
        decimal_places=6,
        default="5.000000",
    )
    public_repositories_only = models.BooleanField(default=True)
    allowed_organizations = models.JSONField(default=list, blank=True)
    auto_claim_enabled = models.BooleanField(default=True)
    maximum_active_jobs = models.PositiveSmallIntegerField(default=1)
    maximum_execution_minutes = models.PositiveSmallIntegerField(default=45)
    allow_fork_creation = models.BooleanField(default=True)
    allow_new_dependencies = models.BooleanField(default=False)
    allow_database_migrations = models.BooleanField(default=False)
    protected_paths = models.JSONField(default=list, blank=True)
    repository_strategy = models.CharField(
        max_length=24,
        choices=RepositoryStrategy.choices,
        default=RepositoryStrategy.FORK_PR,
    )

    engine_provider = models.CharField(
        max_length=24,
        choices=EngineProvider.choices,
        default=EngineProvider.OPENCODE,
    )
    engine_model = models.CharField(max_length=160, default="zai-org/glm-5.2")
    engine_connected = models.BooleanField(default=False)
    engine_version = models.CharField(max_length=160, blank=True)
    engine_last_checked_at = models.DateTimeField(null=True, blank=True)
    engine_last_error = models.TextField(blank=True)
    engine_connection_metadata = models.JSONField(default=dict, blank=True)

    circle_wallet_id = models.CharField(max_length=80, blank=True, unique=True, null=True)
    circle_wallet_set_id = models.CharField(max_length=80, blank=True)
    worker_wallet_address = models.CharField(
        max_length=42,
        blank=True,
        validators=[evm_address_validator],
    )
    wallet_blockchain = models.CharField(max_length=32, default="ARC-TESTNET")
    wallet_account_type = models.CharField(max_length=8, default="SCA")

    payout_wallet_address = models.CharField(
        max_length=42,
        blank=True,
        validators=[evm_address_validator],
    )
    github_username = models.CharField(max_length=80, blank=True)
    github_connected = models.BooleanField(default=False)

    contract_authorised = models.BooleanField(default=False)
    contract_authorisation_idempotency_key = models.UUIDField(
        null=True, blank=True, editable=False
    )
    contract_authorisation_circle_transaction_id = models.CharField(
        max_length=80, blank=True
    )
    contract_authorisation_tx_hash = models.CharField(max_length=66, blank=True)
    contract_authorisation_raw_transaction = models.TextField(blank=True)
    contract_authorisation_nonce = models.PositiveBigIntegerField(null=True, blank=True)
    provisioning_stage = models.CharField(max_length=48, default="PROFILE")
    provisioning_error = models.TextField(blank=True)
    test_assignment_passed = models.BooleanField(default=False)
    discovery_enabled = models.BooleanField(default=False)
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["owner_type", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["worker_wallet_address"],
                condition=~models.Q(worker_wallet_address=""),
                name="uniq_worker_operational_wallet_address",
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        errors = {}

        if self.owner_type == self.OwnerType.EXTERNAL and not self.owner_user_id:
            errors["owner_user"] = "An external worker must have an owner user."
        if self.owner_type == self.OwnerType.VEYRA and self.owner_user_id:
            errors["owner_user"] = "A Veyra-owned worker must not have an external owner user."

        if self.agent_role == self.AgentRole.VERIFIER:
            # Verifier agents review immutable worker submissions. They never
            # enter the paid-worker discovery or auto-claim pool and do not
            # need a worker payout wallet or worker contract authorisation.
            self.auto_claim_enabled = False
            self.discovery_enabled = False
        elif self.status != self.Status.ACTIVE:
            # New and onboarding workers must not auto-claim merely because
            # the database field's historical default is True. Activation
            # explicitly enables execution later.
            self.auto_claim_enabled = False
            self.discovery_enabled = False

        capability_limits = {
            "languages": 2,
            "frameworks": 3,
            "testing_tools": 2,
            "task_types": 3,
        }
        capability_values = []
        for field_name, limit in capability_limits.items():
            value = getattr(self, field_name)
            if not isinstance(value, list):
                errors[field_name] = f"{field_name.replace('_', ' ').title()} must be a list."
                continue
            cleaned = []
            seen = set()
            for item in value:
                if not isinstance(item, str) or not item.strip():
                    errors[field_name] = "Every capability must be a non-empty string."
                    break
                normalised = item.strip()
                key = normalised.casefold()
                if key not in seen:
                    seen.add(key)
                    cleaned.append(normalised)
            if len(cleaned) > limit:
                errors[field_name] = f"Select no more than {limit}."
            setattr(self, field_name, cleaned)
            capability_values.extend(cleaned)

        if len(capability_values) > 10:
            errors["skills"] = "An agent may have no more than ten focused capability tags."

        if not isinstance(self.skills, list):
            errors["skills"] = "Skills must be a list."
        else:
            cleaned_skills = []
            seen = set()
            for skill in [*capability_values, *self.skills]:
                if not isinstance(skill, str) or not skill.strip():
                    errors["skills"] = "Every skill must be a non-empty string."
                    break
                normalised = skill.strip()
                key = normalised.casefold()
                if key not in seen:
                    seen.add(key)
                    cleaned_skills.append(normalised)
            if "skills" not in errors:
                if not cleaned_skills:
                    errors["skills"] = "Add at least one worker capability."
                else:
                    self.skills = cleaned_skills

        for field_name in ("allowed_organizations", "protected_paths"):
            value = getattr(self, field_name)
            if not isinstance(value, list):
                errors[field_name] = f"{field_name.replace('_', ' ').title()} must be a list."
                continue
            cleaned = []
            seen = set()
            for item in value:
                if not isinstance(item, str) or not item.strip():
                    errors[field_name] = "Every entry must be a non-empty string."
                    break
                normalised = item.strip()
                key = normalised.casefold()
                if key not in seen:
                    seen.add(key)
                    cleaned.append(normalised)
            setattr(self, field_name, cleaned)

        if self.minimum_budget_usdc is not None and self.minimum_budget_usdc <= 0:
            errors["minimum_budget_usdc"] = "Minimum budget must be greater than zero."
        if self.maximum_budget_usdc is not None and self.maximum_budget_usdc <= 0:
            errors["maximum_budget_usdc"] = "Maximum budget must be greater than zero."
        if (
            self.minimum_budget_usdc is not None
            and self.maximum_budget_usdc is not None
            and self.maximum_budget_usdc < self.minimum_budget_usdc
        ):
            errors["maximum_budget_usdc"] = "Maximum budget must be at least the minimum budget."
        if not 1 <= self.maximum_active_jobs <= 10:
            errors["maximum_active_jobs"] = "Maximum active jobs must be between 1 and 10."
        if not 10 <= self.maximum_execution_minutes <= 180:
            errors["maximum_execution_minutes"] = "Execution time must be between 10 and 180 minutes."
        if (
            self.auto_claim_enabled
            and (
                self.agent_role != self.AgentRole.WORKER
                or self.status != self.Status.ACTIVE
            )
        ):
            errors["auto_claim_enabled"] = (
                "Auto-claim is available only to an ACTIVE worker agent."
            )

        if self.wallet_blockchain != "ARC-TESTNET":
            errors["wallet_blockchain"] = "The MVP worker wallet must use ARC-TESTNET."
        if self.wallet_account_type != "SCA":
            errors["wallet_account_type"] = "The MVP worker wallet must use an SCA account."

        if self.engine_connected:
            if self.engine_provider not in {
                self.EngineProvider.OPENCODE,
                self.EngineProvider.CUSTOM,
            }:
                errors["engine_provider"] = "Select a supported worker runtime."
            if not self.engine_model.strip():
                errors["engine_model"] = "A connected engine must have a runtime identifier."
            if not self.engine_version.strip():
                errors["engine_version"] = "A connected engine must have a detected version."
            if not self.engine_last_checked_at:
                errors["engine_last_checked_at"] = (
                    "A connected engine must have a successful health-check time."
                )

        if not isinstance(self.engine_connection_metadata, dict):
            errors["engine_connection_metadata"] = "Engine metadata must be an object."

        if self.status == self.Status.ACTIVE:
            if self.agent_role == self.AgentRole.VERIFIER:
                required = {
                    "engine_connected": self.engine_connected,
                    "test_assignment_passed": self.test_assignment_passed,
                }
                subject = "Verifier"
            else:
                required = {
                    "engine_connected": self.engine_connected,
                    "worker_wallet_address": bool(self.worker_wallet_address),
                    "payout_wallet_address": bool(self.payout_wallet_address),
                    "contract_authorised": self.contract_authorised,
                    "test_assignment_passed": self.test_assignment_passed,
                }
                subject = "Worker"

            missing = [name for name, ready in required.items() if not ready]
            if missing:
                errors["status"] = (
                    f"{subject} cannot be ACTIVE until onboarding is complete: "
                    + ", ".join(missing)
                )

        if self.discovery_enabled and (
            self.agent_role != self.AgentRole.WORKER
            or self.status != self.Status.ACTIVE
        ):
            errors["discovery_enabled"] = (
                "Only an ACTIVE worker agent can discover jobs."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        if self.status == self.Status.ACTIVE and self.activated_at is None:
            self.activated_at = timezone.now()
        elif self.status != self.Status.ACTIVE:
            self.discovery_enabled = False
            self.auto_claim_enabled = False
        super().save(*args, **kwargs)


class HostedAgentConnection(TimeStampedModel):
    """Owner-hosted runtime identity connected through a one-time copy link.

    Veyra stores only public runtime metadata and a hash of the long-lived
    runtime credential. The owner's AI provider key remains on the runtime.
    """

    class Status(models.TextChoices):
        CONNECTING = "CONNECTING", "Connecting"
        CONNECTED = "CONNECTED", "Connected"
        UNHEALTHY = "UNHEALTHY", "Unhealthy"
        DISCONNECTED = "DISCONNECTED", "Disconnected"
        REVOKED = "REVOKED", "Revoked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    worker = models.OneToOneField(
        WorkerAgent,
        related_name="hosted_connection",
        on_delete=models.CASCADE,
    )
    runtime_id = models.CharField(max_length=160, unique=True)
    runtime_url = models.URLField(max_length=500)
    public_key = models.TextField()
    public_key_fingerprint = models.CharField(max_length=64, unique=True)
    protocol_version = models.PositiveSmallIntegerField(default=1)
    runtime_version = models.CharField(max_length=64)
    provider = models.CharField(max_length=80)
    model_name = models.CharField(max_length=160)
    provider_ready = models.BooleanField(default=False)
    capabilities = models.JSONField(default=dict, blank=True)
    credential_hash = models.CharField(max_length=64)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CONNECTING,
    )
    connected_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=240, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-connected_at", "-created_at"]
        indexes = [
            models.Index(
                fields=["status", "last_seen_at"],
                name="workers_hos_status_3a5d7e_idx",
            ),
            models.Index(
                fields=["worker", "status"],
                name="workers_hos_worker_6cb5e0_idx",
            ),
        ]

    def __str__(self):
        return f"{self.worker.name} · {self.runtime_id}"

    def clean(self):
        errors = {}
        if not isinstance(self.capabilities, dict):
            errors["capabilities"] = "Runtime capabilities must be an object."
        if not isinstance(self.metadata, dict):
            errors["metadata"] = "Runtime metadata must be an object."
        if self.status == self.Status.CONNECTED and not self.connected_at:
            errors["connected_at"] = "A connected runtime must record its connection time."
        if self.status == self.Status.REVOKED and not self.revoked_at:
            errors["revoked_at"] = "A revoked runtime must record its revocation time."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class RunnerDevice(TimeStampedModel):
    """A control-plane identity for a Veyra execution runtime.

    Owner-hosted Runners use a runner-only keypair whose private key stays on
    the owner's machine. Veyra-hosted runtimes use an internal managed identity.
    Neither identity is an Arc wallet and neither should ever hold funds.
    """

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        REVOKED = "REVOKED", "Revoked"

    class Health(models.TextChoices):
        HEALTHY = "HEALTHY", "Healthy"
        UNHEALTHY = "UNHEALTHY", "Unhealthy"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="runner_devices",
        on_delete=models.PROTECT,
    )
    name = models.CharField(max_length=120)
    device_address = models.CharField(
        max_length=42,
        unique=True,
        validators=[evm_address_validator],
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    runner_version = models.CharField(max_length=64, blank=True)
    os_name = models.CharField(max_length=80, blank=True)
    os_version = models.CharField(max_length=120, blank=True)
    architecture = models.CharField(max_length=40, blank=True)
    python_version = models.CharField(max_length=40, blank=True)
    health = models.CharField(
        max_length=16,
        choices=Health.choices,
        default=Health.UNHEALTHY,
    )
    health_message = models.CharField(max_length=240, blank=True)
    tools = models.JSONField(default=dict, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name", "created_at"]
        indexes = [
            models.Index(fields=["owner_user", "status"]),
            models.Index(fields=["last_seen_at"]),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        errors = {}
        if not isinstance(self.tools, dict):
            errors["tools"] = "Runner tools must be an object."
        if self.status == self.Status.REVOKED and self.revoked_at is None:
            errors["revoked_at"] = "A revoked runner must record when it was revoked."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.device_address = self.device_address.lower()
        self.full_clean()
        super().save(*args, **kwargs)


class RunnerRequestNonce(TimeStampedModel):
    """A durable replay guard for one signed Runner request."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    runner = models.ForeignKey(
        RunnerDevice,
        related_name="request_nonces",
        on_delete=models.CASCADE,
    )
    nonce_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["runner", "nonce_hash"],
                name="uniq_runner_request_nonce",
            ),
        ]
        indexes = [
            models.Index(
                fields=["expires_at"],
                name="runner_nonce_expiry_idx",
            ),
        ]


class RunnerAgentBinding(TimeStampedModel):
    """Links one agent to either a Veyra-hosted or owner-hosted runtime."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        REVOKED = "REVOKED", "Revoked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    worker = models.OneToOneField(
        WorkerAgent,
        related_name="runtime_binding",
        on_delete=models.CASCADE,
    )
    runner = models.ForeignKey(
        RunnerDevice,
        related_name="agent_bindings",
        on_delete=models.PROTECT,
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    paired_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-paired_at"]
        indexes = [
            models.Index(fields=["runner", "status"]),
            models.Index(fields=["worker", "status"]),
        ]

    def __str__(self):
        return f"{self.runner.name} -> {self.worker.name}"

    def clean(self):
        errors = {}
        if self.runner.owner_user_id != self.worker.owner_user_id:
            errors["runner"] = "Runner and agent must belong to the same owner."
        if self.status == self.Status.REVOKED and self.revoked_at is None:
            errors["revoked_at"] = "A revoked binding must record when it was revoked."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class RunnerPairingCode(TimeStampedModel):
    """A short-lived, one-time bootstrap code used to bind a runner to an agent.

    Only a keyed hash is stored. The raw code is returned once to the owner and
    is never written to logs or persisted in plaintext.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    worker = models.ForeignKey(
        WorkerAgent,
        related_name="runtime_pairing_codes",
        on_delete=models.CASCADE,
    )
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="runner_pairing_codes",
        on_delete=models.CASCADE,
    )
    code_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["worker", "expires_at"]),
            models.Index(fields=["owner_user", "expires_at"]),
        ]

    def __str__(self):
        return f"Pairing code for {self.worker.name}"

    @property
    def is_available(self):
        now = timezone.now()
        return (
            self.consumed_at is None
            and self.cancelled_at is None
            and self.expires_at > now
        )


class WorkerTestAssignment(TimeStampedModel):
    """A controlled GitHub issue used to prove a worker is ready.

    This model stores public repository metadata and sanitized execution output.
    GitHub tokens, Circle secrets, API keys, and private keys are never stored.
    """

    class Status(models.TextChoices):
        PREPARED = "PREPARED", "Prepared"
        RUNNING = "RUNNING", "Running"
        ENGINE_COMPLETED = "ENGINE_COMPLETED", "Engine completed"
        TESTS_PASSED = "TESTS_PASSED", "Tests passed"
        PR_OPENED = "PR_OPENED", "Pull request opened"
        PASSED = "PASSED", "Passed"
        FAILED = "FAILED", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    worker = models.ForeignKey(
        WorkerAgent,
        related_name="test_assignments",
        on_delete=models.PROTECT,
    )
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.PREPARED,
    )

    issue_url = models.URLField()
    repository_url = models.URLField()
    source_owner = models.CharField(max_length=120)
    source_repository = models.CharField(max_length=120)
    issue_number = models.PositiveBigIntegerField()
    issue_title = models.CharField(max_length=240)
    issue_body = models.TextField(blank=True)
    acceptance_criteria = models.JSONField(default=list, blank=True)
    base_branch = models.CharField(max_length=120, default="main")

    fork_owner = models.CharField(max_length=120, blank=True)
    fork_repository = models.CharField(max_length=120, blank=True)
    branch_name = models.CharField(max_length=180, blank=True)
    workspace_name = models.CharField(max_length=180, blank=True)

    baseline_test_command = models.CharField(max_length=240, blank=True)
    post_test_command = models.CharField(max_length=240, blank=True)
    baseline_test_passed = models.BooleanField(null=True, blank=True)
    post_test_passed = models.BooleanField(default=False)

    changed_files = models.JSONField(default=list, blank=True)
    commit_sha = models.CharField(max_length=64, blank=True)
    pull_request_number = models.PositiveBigIntegerField(null=True, blank=True)
    pull_request_url = models.URLField(blank=True)

    engine_output = models.TextField(blank=True)
    baseline_test_output = models.TextField(blank=True)
    test_output = models.TextField(blank=True)
    failure_stage = models.CharField(max_length=80, blank=True)
    failure_message = models.TextField(blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["worker", "status"]),
            models.Index(
                fields=["source_owner", "source_repository", "issue_number"]
            ),
        ]

    def __str__(self):
        return (
            f"{self.worker.name}: "
            f"{self.source_owner}/{self.source_repository}#{self.issue_number}"
        )

    def clean(self):
        errors = {}

        if not isinstance(self.acceptance_criteria, list):
            errors["acceptance_criteria"] = "Acceptance criteria must be a list."
        if not isinstance(self.changed_files, list):
            errors["changed_files"] = "Changed files must be a list."

        if self.status in {self.Status.PR_OPENED, self.Status.PASSED}:
            if not self.pull_request_url or not self.pull_request_number:
                errors["pull_request_url"] = (
                    "A pull request URL and number are required at this stage."
                )

        if self.status == self.Status.PASSED:
            if not self.post_test_passed:
                errors["post_test_passed"] = (
                    "The test assignment cannot pass until post-change tests pass."
                )
            if not self.commit_sha:
                errors["commit_sha"] = "A passing assignment must have a commit SHA."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class WorkerQualificationRun(TimeStampedModel):
    """A short-lived automatic qualification delivered to an owner-hosted runtime.

    The owner's AI key and runtime credential are never stored here. Veyra stores
    only the task state, submitted source, a signed result, and sanitized output.
    """

    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        LEASED = "LEASED", "Leased to runtime"
        SUBMITTED = "SUBMITTED", "Submitted"
        PASSED = "PASSED", "Passed"
        FAILED = "FAILED", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    worker = models.ForeignKey(
        WorkerAgent,
        related_name="automatic_qualification_runs",
        on_delete=models.PROTECT,
    )
    attempt_number = models.PositiveSmallIntegerField(default=1)
    task_version = models.CharField(max_length=64, default="python-health-v1")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.QUEUED,
    )
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    provider = models.CharField(max_length=80, blank=True)
    model_name = models.CharField(max_length=160, blank=True)
    runtime_version = models.CharField(max_length=64, blank=True)
    submitted_files = models.JSONField(default=list, blank=True)
    test_return_code = models.IntegerField(null=True, blank=True)
    test_output = models.TextField(blank=True)
    result_signature = models.TextField(blank=True)
    failure_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["worker", "attempt_number"],
                name="uniq_worker_qualification_attempt",
            )
        ]
        indexes = [
            models.Index(
                fields=["worker", "status"],
                name="wrk_qual_worker_status_idx",
            ),
            models.Index(
                fields=["status", "lease_expires_at"],
                name="wrk_qual_status_lease_idx",
            ),
        ]

    def __str__(self):
        return f"{self.worker.name} qualification attempt {self.attempt_number}"

    def clean(self):
        if not isinstance(self.submitted_files, list):
            raise ValidationError(
                {"submitted_files": "Submitted files must be a list."}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class ExecutionLayerState(TimeStampedModel):
    """Public, secret-free health projection for the automatic controller."""

    key = models.CharField(primary_key=True, max_length=32, default="default")
    instance_id = models.UUIDField(null=True, blank=True, editable=False)
    process_id = models.PositiveIntegerField(default=0)
    cycle_number = models.PositiveBigIntegerField(default=0)
    running = models.BooleanField(default=False)
    last_cycle_started_at = models.DateTimeField(null=True, blank=True)
    last_cycle_finished_at = models.DateTimeField(null=True, blank=True)
    next_cycle_at = models.DateTimeField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    consecutive_failures = models.PositiveSmallIntegerField(default=0)
    last_error_code = models.CharField(max_length=80, blank=True)
    last_error_message = models.CharField(max_length=300, blank=True)
    last_result = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"Execution layer {self.key}"


class WorkerJobQueueItem(TimeStampedModel):
    """A sanitized worker-side projection of an eligible Veyra job.

    Queue items never contain Circle credentials, GitHub tokens, OpenCode
    credentials, private keys, or recovery material. They only store public
    repository metadata, onchain state, and deterministic eligibility results.
    """

    class Status(models.TextChoices):
        DISCOVERED = "DISCOVERED", "Discovered"
        QUEUED = "QUEUED", "Queued for claim"
        DEFERRED = "DEFERRED", "Deferred"
        INELIGIBLE = "INELIGIBLE", "Ineligible"
        STALE = "STALE", "No longer open"
        BLOCKED = "BLOCKED", "Blocked by task freshness guard"
        DUPLICATE = "DUPLICATE", "Duplicate repository issue"
        CLAIM_PENDING = "CLAIM_PENDING", "Claim pending"
        CLAIMED = "CLAIMED", "Claimed"
        LEASED = "LEASED", "Leased to hosted runtime"
        EXECUTING = "EXECUTING", "Executing"
        RESULT_RECEIVED = "RESULT_RECEIVED", "Runtime result received"
        SUBMISSION_PENDING = "SUBMISSION_PENDING", "Submission pending"
        SUBMITTED = "SUBMITTED", "Submitted"
        VERIFYING = "VERIFYING", "Independent verification"
        SETTLING = "SETTLING", "Settlement pending"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    class Source(models.TextChoices):
        FAST_PATH = "FAST_PATH", "JobCreated fast path"
        RECONCILIATION = "RECONCILIATION", "Periodic reconciliation"
        MANUAL = "MANUAL", "Manual discovery"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    worker = models.ForeignKey(
        WorkerAgent,
        related_name="job_queue_items",
        on_delete=models.PROTECT,
    )
    job = models.ForeignKey(
        "jobs.VeyraJob",
        related_name="worker_queue_items",
        on_delete=models.PROTECT,
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.DISCOVERED,
    )
    source = models.CharField(
        max_length=24,
        choices=Source.choices,
        default=Source.RECONCILIATION,
    )

    eligibility_passed = models.BooleanField(default=False)
    eligibility_code = models.CharField(max_length=64, blank=True)
    eligibility_detail = models.CharField(max_length=300, blank=True)
    priority_score = models.IntegerField(default=0)
    required_skills = models.JSONField(default=list, blank=True)
    matched_skills = models.JSONField(default=list, blank=True)

    onchain_status = models.CharField(max_length=24, blank=True)
    onchain_snapshot = models.JSONField(default=dict, blank=True)
    github_freshness_code = models.CharField(max_length=64, blank=True)
    github_snapshot = models.JSONField(default=dict, blank=True)
    github_last_checked_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    queued_at = models.DateTimeField(null=True, blank=True)
    matching_retry_count = models.PositiveSmallIntegerField(default=0)
    matching_next_retry_at = models.DateTimeField(null=True, blank=True)

    # Public claim lifecycle metadata only. Secrets remain in runtime settings.
    claim_idempotency_key = models.UUIDField(null=True, blank=True, editable=False)
    claim_attempt_count = models.PositiveSmallIntegerField(default=0)
    claim_circle_transaction_id = models.CharField(
        max_length=80, null=True, blank=True, unique=True
    )
    claim_circle_state = models.CharField(max_length=32, blank=True)
    claim_arc_transaction_hash = models.CharField(
        max_length=66, null=True, blank=True, unique=True
    )
    claim_receipt_block_number = models.PositiveBigIntegerField(null=True, blank=True)
    claim_failure_stage = models.CharField(max_length=80, blank=True)
    claim_failure_message = models.TextField(blank=True)
    claim_started_at = models.DateTimeField(null=True, blank=True)
    claim_submitted_at = models.DateTimeField(null=True, blank=True)
    claim_last_checked_at = models.DateTimeField(null=True, blank=True)
    claim_confirmed_at = models.DateTimeField(null=True, blank=True)

    # Public coding execution metadata. Runtime tokens and engine credentials
    # never enter this model.
    execution_attempt_count = models.PositiveSmallIntegerField(default=0)
    execution_branch_name = models.CharField(max_length=180, blank=True)
    execution_workspace_name = models.CharField(max_length=180, blank=True)
    execution_baseline_test_command = models.CharField(max_length=240, blank=True)
    execution_post_test_command = models.CharField(max_length=240, blank=True)
    execution_baseline_test_passed = models.BooleanField(null=True, blank=True)
    execution_post_test_passed = models.BooleanField(default=False)
    execution_changed_files = models.JSONField(default=list, blank=True)
    execution_commit_sha = models.CharField(max_length=64, blank=True)
    execution_pull_request_number = models.PositiveBigIntegerField(null=True, blank=True)
    execution_pull_request_url = models.URLField(blank=True)
    execution_engine_output = models.TextField(blank=True)
    execution_baseline_test_output = models.TextField(blank=True)
    execution_test_output = models.TextField(blank=True)
    execution_failure_stage = models.CharField(max_length=80, blank=True)
    execution_failure_message = models.TextField(blank=True)
    execution_started_at = models.DateTimeField(null=True, blank=True)
    execution_completed_at = models.DateTimeField(null=True, blank=True)

    # Public submitWork lifecycle metadata. The Circle entity secret and API
    # key remain runtime-only.
    submission_idempotency_key = models.UUIDField(null=True, blank=True, editable=False)
    submission_attempt_count = models.PositiveSmallIntegerField(default=0)
    submission_commit_hash = models.CharField(max_length=66, blank=True)
    submission_deliverable_hash = models.CharField(max_length=66, blank=True)
    submission_circle_transaction_id = models.CharField(
        max_length=80, null=True, blank=True, unique=True
    )
    submission_circle_state = models.CharField(max_length=32, blank=True)
    submission_arc_transaction_hash = models.CharField(
        max_length=66, null=True, blank=True, unique=True
    )
    submission_receipt_block_number = models.PositiveBigIntegerField(null=True, blank=True)
    submission_failure_stage = models.CharField(max_length=80, blank=True)
    submission_failure_message = models.TextField(blank=True)
    submission_started_at = models.DateTimeField(null=True, blank=True)
    submission_submitted_at = models.DateTimeField(null=True, blank=True)
    submission_last_checked_at = models.DateTimeField(null=True, blank=True)
    submission_confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-priority_score", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["worker", "job"],
                name="uniq_worker_job_queue_item",
            ),
        ]
        indexes = [
            models.Index(fields=["worker", "status"]),
            models.Index(fields=["status", "priority_score"]),
        ]

    def __str__(self):
        return f"{self.worker.name}: Arc job {self.job.onchain_job_id} ({self.status})"

    def clean(self):
        errors = {}
        if not isinstance(self.required_skills, list):
            errors["required_skills"] = "Required skills must be a list."
        if not isinstance(self.matched_skills, list):
            errors["matched_skills"] = "Matched skills must be a list."
        if not isinstance(self.onchain_snapshot, dict):
            errors["onchain_snapshot"] = "The onchain snapshot must be an object."
        if not isinstance(self.github_snapshot, dict):
            errors["github_snapshot"] = "The GitHub snapshot must be an object."
        if not isinstance(self.execution_changed_files, list):
            errors["execution_changed_files"] = "Execution changed files must be a list."
        if self.status == self.Status.QUEUED and not self.eligibility_passed:
            errors["status"] = "Only an eligible job can be queued."
        if self.status == self.Status.CLAIM_PENDING:
            if not self.claim_idempotency_key:
                errors["claim_idempotency_key"] = (
                    "A pending claim requires a stable idempotency key."
                )
            if not self.claim_started_at:
                errors["claim_started_at"] = "A pending claim requires a start time."
        if self.status in {
            self.Status.CLAIMED,
            self.Status.LEASED,
            self.Status.EXECUTING,
            self.Status.RESULT_RECEIVED,
            self.Status.SUBMISSION_PENDING,
            self.Status.SUBMITTED,
            self.Status.VERIFYING,
            self.Status.SETTLING,
            self.Status.COMPLETED,
        }:
            if not self.claim_arc_transaction_hash:
                errors["claim_arc_transaction_hash"] = (
                    "A claimed job lifecycle requires an Arc claim transaction hash."
                )
            if not self.claim_confirmed_at:
                errors["claim_confirmed_at"] = (
                    "A claimed job lifecycle requires an onchain claim confirmation time."
                )
        if self.status == self.Status.EXECUTING:
            if not self.execution_started_at:
                errors["execution_started_at"] = "Execution requires a start time."
            if not self.execution_branch_name or not self.execution_workspace_name:
                errors["execution_branch_name"] = (
                    "Execution requires deterministic branch and workspace names."
                )
        if self.status in {
            self.Status.RESULT_RECEIVED,
            self.Status.SUBMISSION_PENDING,
            self.Status.SUBMITTED,
            self.Status.VERIFYING,
            self.Status.SETTLING,
            self.Status.COMPLETED,
        }:
            if not self.execution_post_test_passed:
                errors["execution_post_test_passed"] = (
                    "Submission requires passing post-change tests."
                )
            if not self.execution_commit_sha:
                errors["execution_commit_sha"] = "Submission requires a Git commit SHA."
            if not self.execution_pull_request_url or not self.execution_pull_request_number:
                errors["execution_pull_request_url"] = (
                    "Submission requires an open pull request record."
                )
        if self.status == self.Status.SUBMISSION_PENDING:
            if not self.execution_completed_at:
                errors["execution_completed_at"] = (
                    "Submission pending requires completed coding execution."
                )
        if self.status == self.Status.SUBMITTED:
            if self.onchain_status != "SUBMITTED":
                errors["onchain_status"] = (
                    "A submitted queue item must record SUBMITTED onchain status."
                )
            if not self.submission_arc_transaction_hash:
                errors["submission_arc_transaction_hash"] = (
                    "A submitted job requires an Arc transaction hash."
                )
            if not self.submission_confirmed_at:
                errors["submission_confirmed_at"] = (
                    "A submitted job requires an onchain confirmation time."
                )
            if not self.submission_commit_hash or not self.submission_deliverable_hash:
                errors["submission_commit_hash"] = (
                    "A submitted job requires commit and deliverable hashes."
                )
        if self.eligibility_passed and self.eligibility_code != "ELIGIBLE":
            errors["eligibility_code"] = (
                "A passing eligibility result must use the ELIGIBLE code."
            )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

class WorkerJobAssignment(TimeStampedModel):
    """Authoritative one-agent assignment for a funded Veyra job.

    A job may have many eligible queue items, but only one assignment record.
    The one-to-one job constraint is the database race lock that prevents two
    agents from receiving or executing the same normal marketplace job.
    """

    class Status(models.TextChoices):
        RESERVED = "RESERVED", "Reserved"
        CLAIMING = "CLAIMING", "Claiming on Arc"
        CLAIMED = "CLAIMED", "Claimed"
        LEASED = "LEASED", "Leased to runtime"
        EXECUTING = "EXECUTING", "Executing"
        RESULT_RECEIVED = "RESULT_RECEIVED", "Result received"
        SUBMITTING = "SUBMITTING", "Submitting on Arc"
        SUBMITTED = "SUBMITTED", "Submitted"
        VERIFYING = "VERIFYING", "Verifying"
        SETTLING = "SETTLING", "Settling"
        COMPLETED = "COMPLETED", "Completed"
        RELEASED = "RELEASED", "Released for reassignment"
        FAILED = "FAILED", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField(
        "jobs.VeyraJob", related_name="worker_assignment", on_delete=models.PROTECT
    )
    worker = models.ForeignKey(
        WorkerAgent, related_name="job_assignments", on_delete=models.PROTECT
    )
    queue_item = models.OneToOneField(
        WorkerJobQueueItem, related_name="assignment", on_delete=models.PROTECT
    )
    status = models.CharField(
        max_length=32, choices=Status.choices, default=Status.RESERVED
    )
    assignment_attempt = models.PositiveSmallIntegerField(default=1)
    candidate_count = models.PositiveSmallIntegerField(default=1)
    matching_score = models.IntegerField(default=0)
    fairness_rank = models.PositiveIntegerField(default=0)
    selection_reason = models.CharField(max_length=300, blank=True)
    selection_history = models.JSONField(default=list, blank=True)

    reservation_token = models.UUIDField(default=uuid.uuid4, editable=False)
    reserved_at = models.DateTimeField(default=timezone.now)
    reserved_until = models.DateTimeField()

    execution_lease_id = models.UUIDField(null=True, blank=True, editable=False)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    leased_at = models.DateTimeField(null=True, blank=True)
    runtime_last_seen_at = models.DateTimeField(null=True, blank=True)
    execution_started_at = models.DateTimeField(null=True, blank=True)
    execution_completed_at = models.DateTimeField(null=True, blank=True)

    evidence_hash = models.CharField(max_length=66, blank=True)
    runtime_signature = models.TextField(blank=True)
    execution_evidence = models.JSONField(default=dict, blank=True)

    verification_status = models.CharField(max_length=24, blank=True)
    verification_report = models.JSONField(default=dict, blank=True)
    verification_report_hash = models.CharField(max_length=66, blank=True)
    verification_evidence_hash = models.CharField(max_length=66, blank=True)
    verification_reason_hash = models.CharField(max_length=66, blank=True)
    verification_started_at = models.DateTimeField(null=True, blank=True)
    verification_completed_at = models.DateTimeField(null=True, blank=True)

    settlement_transaction_hash = models.CharField(
        max_length=66, blank=True, unique=True, null=True
    )
    settlement_raw_transaction = models.TextField(blank=True)
    settlement_nonce = models.PositiveBigIntegerField(null=True, blank=True)
    settlement_receipt_block_number = models.PositiveBigIntegerField(null=True, blank=True)
    settlement_started_at = models.DateTimeField(null=True, blank=True)
    settlement_confirmed_at = models.DateTimeField(null=True, blank=True)

    failure_stage = models.CharField(max_length=80, blank=True)
    failure_message = models.TextField(blank=True)
    failure_history = models.JSONField(default=list, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["status", "reserved_until"],
                name="workers_wor_status_66c05f_idx",
            ),
            models.Index(
                fields=["worker", "status"],
                name="workers_wor_worker__fd365e_idx",
            ),
        ]

    def __str__(self):
        return f"Arc job {self.job.onchain_job_id} -> {self.worker.name} ({self.status})"

    def clean(self):
        errors = {}
        if self.queue_item_id and self.worker_id and self.queue_item.worker_id != self.worker_id:
            errors["queue_item"] = "The queue item belongs to a different worker."
        if self.queue_item_id and self.job_id and self.queue_item.job_id != self.job_id:
            errors["queue_item"] = "The queue item belongs to a different job."
        if not isinstance(self.selection_history, list):
            errors["selection_history"] = "Selection history must be a list."
        if not isinstance(self.execution_evidence, dict):
            errors["execution_evidence"] = "Execution evidence must be an object."
        if not isinstance(self.verification_report, dict):
            errors["verification_report"] = "Verification report must be an object."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class WorkerVerificationAssignment(TimeStampedModel):
    """One independent verifier-agent review for a submitted worker job.

    The verifier receives read-only access to the exact submitted commit. Its
    AI provider key and Ed25519 private key stay on the verifier runtime. Veyra
    stores only the signed structured verdict and sanitized evidence.
    """

    class Status(models.TextChoices):
        RESERVED = "RESERVED", "Verifier reserved"
        LEASED = "LEASED", "Leased to verifier runtime"
        RUNNING = "RUNNING", "Verifier running"
        SUBMITTED = "SUBMITTED", "Verdict submitted"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        INCONCLUSIVE = "INCONCLUSIVE", "Inconclusive"
        EXPIRED = "EXPIRED", "Lease expired"
        FAILED = "FAILED", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    worker_assignment = models.OneToOneField(
        WorkerJobAssignment,
        related_name="verifier_assignment",
        on_delete=models.PROTECT,
    )
    verifier = models.ForeignKey(
        WorkerAgent,
        related_name="verification_assignments",
        on_delete=models.PROTECT,
    )
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.RESERVED,
    )
    assignment_attempt = models.PositiveSmallIntegerField(default=1)
    matching_score = models.IntegerField(default=0)
    candidate_count = models.PositiveSmallIntegerField(default=1)
    fairness_rank = models.PositiveIntegerField(default=1)
    selection_reason = models.CharField(max_length=300, blank=True)
    selection_history = models.JSONField(default=list, blank=True)

    reservation_token = models.UUIDField(default=uuid.uuid4, editable=False)
    reserved_at = models.DateTimeField(default=timezone.now)
    reserved_until = models.DateTimeField()
    lease_id = models.UUIDField(null=True, blank=True, editable=False)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    leased_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    verdict = models.CharField(max_length=20, blank=True)
    report = models.JSONField(default=dict, blank=True)
    report_hash = models.CharField(max_length=66, blank=True)
    evidence_hash = models.CharField(max_length=66, blank=True)
    runtime_signature = models.TextField(blank=True)
    failure_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["status", "reserved_until"],
                name="workers_ver_status_res_idx",
            ),
            models.Index(
                fields=["verifier", "status"],
                name="workers_ver_agent_status_idx",
            ),
        ]

    def __str__(self):
        return (
            f"Arc job {self.worker_assignment.job.onchain_job_id} verified by "
            f"{self.verifier.name} ({self.status})"
        )

    def clean(self):
        errors = {}
        if self.verifier_id:
            if self.verifier.agent_role != WorkerAgent.AgentRole.VERIFIER:
                errors["verifier"] = "The selected agent is not a verifier agent."
            if self.worker_assignment_id:
                worker = self.worker_assignment.worker
                if worker.id == self.verifier_id:
                    errors["verifier"] = "A worker cannot verify its own submission."
                if (
                    worker.owner_user_id
                    and self.verifier.owner_user_id
                    and worker.owner_user_id == self.verifier.owner_user_id
                ):
                    errors["verifier"] = (
                        "A verifier cannot be controlled by the worker owner."
                    )
        if not isinstance(self.report, dict):
            errors["report"] = "The verifier report must be an object."
        if not isinstance(self.selection_history, list):
            errors["selection_history"] = "Verifier selection history must be a list."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class WorkerReputationSnapshot(TimeStampedModel):
    """Last authoritative Arc reputation state for one agent wallet."""

    worker = models.OneToOneField(
        WorkerAgent, related_name="reputation_snapshot", on_delete=models.CASCADE
    )
    karma_score = models.PositiveBigIntegerField(default=0)
    completed_jobs = models.PositiveBigIntegerField(default=0)
    failed_jobs = models.PositiveBigIntegerField(default=0)
    abandoned_jobs = models.PositiveBigIntegerField(default=0)
    total_earned_atomic = models.DecimalField(max_digits=40, decimal_places=0, default=0)
    last_job_id = models.PositiveBigIntegerField(null=True, blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-karma_score", "worker_id"]

    def __str__(self):
        return f"{self.worker.name}: {self.karma_score} Karma"
