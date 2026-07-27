import uuid

from django.utils.text import slugify
from rest_framework import serializers

from workers.agent_provisioning import AgentProvisioningError, provision_agent
from workers.hosted_agent_connection import HostedAgentConnectionError, parse_connection_link
from workers.execution_status import worker_execution_snapshot
from workers.models import WorkerAgent
from workers.runtime_status import runtime_snapshot


CAPABILITY_LIMITS = {
    "languages": 2,
    "frameworks": 3,
    "testing_tools": 2,
    "task_types": 3,
}


def _clean_string_list(value, *, field_name: str, maximum: int | None = None):
    if not isinstance(value, list):
        raise serializers.ValidationError(f"{field_name} must be a list.")
    cleaned = []
    seen = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise serializers.ValidationError("Every entry must be a non-empty string.")
        normalised = item.strip()
        key = normalised.casefold()
        if key not in seen:
            seen.add(key)
            cleaned.append(normalised)
    if maximum is not None and len(cleaned) > maximum:
        raise serializers.ValidationError(f"Select no more than {maximum}.")
    return cleaned


def _unique_slug(name: str) -> str:
    base = slugify(name)[:68] or "agent"
    candidate = base
    while WorkerAgent.objects.filter(slug=candidate).exists():
        candidate = f"{base[:59]}-{uuid.uuid4().hex[:8]}"
    return candidate


class WorkerAgentSerializer(serializers.ModelSerializer):
    onboarding = serializers.SerializerMethodField()

    class Meta:
        model = WorkerAgent
        fields = [
            "id",
            "slug",
            "name",
            "description",
            "avatar_url",
            "owner_type",
            "owner_user",
            "agent_role",
            "status",
            "specialisation",
            "languages",
            "frameworks",
            "testing_tools",
            "task_types",
            "skills",
            "minimum_budget_usdc",
            "maximum_budget_usdc",
            "public_repositories_only",
            "allowed_organizations",
            "auto_claim_enabled",
            "maximum_active_jobs",
            "maximum_execution_minutes",
            "allow_fork_creation",
            "allow_new_dependencies",
            "allow_database_migrations",
            "protected_paths",
            "repository_strategy",
            "engine_provider",
            "engine_model",
            "engine_connected",
            "engine_version",
            "engine_last_checked_at",
            "engine_last_error",
            "engine_connection_metadata",
            "circle_wallet_id",
            "circle_wallet_set_id",
            "worker_wallet_address",
            "wallet_blockchain",
            "wallet_account_type",
            "payout_wallet_address",
            "github_username",
            "github_connected",
            "contract_authorised",
            "contract_authorisation_tx_hash",
            "provisioning_stage",
            "provisioning_error",
            "test_assignment_passed",
            "discovery_enabled",
            "activated_at",
            "onboarding",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "engine_connected",
            "engine_version",
            "engine_last_checked_at",
            "engine_last_error",
            "engine_connection_metadata",
            "circle_wallet_id",
            "circle_wallet_set_id",
            "worker_wallet_address",
            "github_connected",
            "contract_authorised",
            "contract_authorisation_tx_hash",
            "provisioning_stage",
            "provisioning_error",
            "test_assignment_passed",
            "discovery_enabled",
            "activated_at",
            "onboarding",
            "created_at",
            "updated_at",
        ]

    def validate_skills(self, value):
        cleaned = _clean_string_list(value, field_name="Skills")
        if not cleaned:
            raise serializers.ValidationError("Add at least one worker skill.")
        return cleaned

    def validate_minimum_budget_usdc(self, value):
        if value <= 0:
            raise serializers.ValidationError("Minimum budget must be greater than zero.")
        return value

    def validate_maximum_active_jobs(self, value):
        if not 1 <= value <= 10:
            raise serializers.ValidationError("Maximum active jobs must be between 1 and 10.")
        return value

    def create(self, validated_data):
        validated_data["status"] = WorkerAgent.Status.PROFILE_READY
        return super().create(validated_data)

    def get_onboarding(self, obj):
        checks = {
            "profile_ready": obj.status != WorkerAgent.Status.SETUP_REQUIRED,
            "runtime_connected": obj.engine_connected,
            "worker_wallet_ready": bool(obj.circle_wallet_id and obj.worker_wallet_address),
            "payout_wallet_ready": bool(obj.payout_wallet_address),
            "contract_authorised": obj.contract_authorised,
            "test_assignment_passed": obj.test_assignment_passed,
        }
        return {
            "phase": 2 if obj.contract_authorised or obj.test_assignment_passed else 1,
            "checks": checks,
            "ready_for_activation": all(checks.values()),
        }


class AgentOwnerWorkerSerializer(serializers.ModelSerializer):
    """Owner-safe agent representation used by the frontend control plane.

    Circle wallet IDs, wallet-set IDs, GitHub credentials, engine secrets, and
    raw engine metadata are intentionally not exposed here.
    """

    onboarding = serializers.SerializerMethodField()
    capability_count = serializers.SerializerMethodField()
    runtime = serializers.SerializerMethodField()
    execution = serializers.SerializerMethodField()
    connection_link = serializers.CharField(
        write_only=True,
        trim_whitespace=True,
        max_length=2000,
        required=False,
    )

    class Meta:
        model = WorkerAgent
        fields = [
            "id",
            "slug",
            "name",
            "description",
            "avatar_url",
            "agent_role",
            "status",
            "specialisation",
            "languages",
            "frameworks",
            "testing_tools",
            "task_types",
            "capability_count",
            "minimum_budget_usdc",
            "maximum_budget_usdc",
            "public_repositories_only",
            "allowed_organizations",
            "auto_claim_enabled",
            "maximum_active_jobs",
            "maximum_execution_minutes",
            "allow_fork_creation",
            "allow_new_dependencies",
            "allow_database_migrations",
            "protected_paths",
            "connection_link",
            "engine_connected",
            "engine_version",
            "engine_last_checked_at",
            "engine_last_error",
            "runtime",
            "execution",
            "worker_wallet_address",
            "wallet_blockchain",
            "wallet_account_type",
            "github_username",
            "github_connected",
            "contract_authorised",
            "contract_authorisation_tx_hash",
            "provisioning_stage",
            "provisioning_error",
            "test_assignment_passed",
            "discovery_enabled",
            "activated_at",
            "onboarding",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "slug",
            "agent_role",
            "status",
            "capability_count",
            "engine_connected",
            "engine_version",
            "engine_last_checked_at",
            "engine_last_error",
            "runtime",
            "execution",
            "worker_wallet_address",
            "wallet_blockchain",
            "wallet_account_type",
            "github_username",
            "github_connected",
            "contract_authorised",
            "contract_authorisation_tx_hash",
            "provisioning_stage",
            "provisioning_error",
            "test_assignment_passed",
            "discovery_enabled",
            "activated_at",
            "onboarding",
            "created_at",
            "updated_at",
        ]

    def validate_connection_link(self, value):
        try:
            parse_connection_link(value)
        except HostedAgentConnectionError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return value

    def validate_languages(self, value):
        return _clean_string_list(value, field_name="Languages", maximum=2)

    def validate_frameworks(self, value):
        return _clean_string_list(value, field_name="Frameworks", maximum=3)

    def validate_testing_tools(self, value):
        return _clean_string_list(value, field_name="Testing tools", maximum=2)

    def validate_task_types(self, value):
        return _clean_string_list(value, field_name="Task types", maximum=3)

    def validate_allowed_organizations(self, value):
        return _clean_string_list(
            value,
            field_name="Allowed organizations",
            maximum=20,
        )

    def validate_protected_paths(self, value):
        return _clean_string_list(value, field_name="Protected paths", maximum=30)

    def validate_minimum_budget_usdc(self, value):
        if value <= 0:
            raise serializers.ValidationError("Minimum budget must be greater than zero.")
        return value

    def validate_maximum_budget_usdc(self, value):
        if value <= 0:
            raise serializers.ValidationError("Maximum budget must be greater than zero.")
        return value

    def validate_maximum_active_jobs(self, value):
        if not 1 <= value <= 3:
            raise serializers.ValidationError(
                "Agent owners may configure between one and three concurrent jobs."
            )
        return value

    def validate_maximum_execution_minutes(self, value):
        if not 10 <= value <= 180:
            raise serializers.ValidationError(
                "Execution time must be between 10 and 180 minutes."
            )
        return value

    def validate(self, attrs):
        instance = getattr(self, "instance", None)
        if instance is None and not str(attrs.get("connection_link") or "").strip():
            raise serializers.ValidationError(
                {"connection_link": "Paste the connection link from the hosted-agent server."}
            )
        minimum = attrs.get(
            "minimum_budget_usdc",
            getattr(instance, "minimum_budget_usdc", None),
        )
        maximum = attrs.get(
            "maximum_budget_usdc",
            getattr(instance, "maximum_budget_usdc", None),
        )
        if minimum is not None and maximum is not None and maximum < minimum:
            raise serializers.ValidationError(
                {"maximum_budget_usdc": "Maximum budget must be at least the minimum budget."}
            )

        capability_fields = ("languages", "frameworks", "testing_tools", "task_types")
        values = []
        for field in capability_fields:
            values.extend(attrs.get(field, getattr(instance, field, [])))
        if not values:
            raise serializers.ValidationError(
                {"languages": "Select at least one focused capability."}
            )
        if len(values) > 10:
            raise serializers.ValidationError(
                {"languages": "An agent may have no more than ten capability tags."}
            )

        auto_claim = attrs.get(
            "auto_claim_enabled",
            getattr(instance, "auto_claim_enabled", False),
        )
        status_value = getattr(instance, "status", WorkerAgent.Status.PROFILE_READY)
        if auto_claim and status_value != WorkerAgent.Status.ACTIVE:
            raise serializers.ValidationError(
                {"auto_claim_enabled": "Auto-claim becomes available after readiness and activation."}
            )
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        connection_link = str(validated_data.pop("connection_link", "") or "").strip()
        capability_values = []
        for field in CAPABILITY_LIMITS:
            capability_values.extend(validated_data.get(field, []))
        validated_data.update(
            {
                "slug": _unique_slug(validated_data["name"]),
                "owner_type": WorkerAgent.OwnerType.EXTERNAL,
                "owner_user": request.user,
                "status": WorkerAgent.Status.PROVISIONING,
                "provisioning_stage": "PROFILE_CREATED",
                "engine_provider": WorkerAgent.EngineProvider.CUSTOM,
                "engine_model": "pending-owner-runtime",
                "skills": capability_values,
                "auto_claim_enabled": False,
                "discovery_enabled": False,
            }
        )
        worker = super().create(validated_data)
        try:
            provision_agent(worker, connection_link=connection_link)
        except AgentProvisioningError:
            # The agent record is deliberately retained with a safe failure
            # status so the owner can retry without creating a duplicate wallet.
            pass
        worker.refresh_from_db()
        return worker

    def update(self, instance, validated_data):
        capability_values = []
        for field in CAPABILITY_LIMITS:
            capability_values.extend(validated_data.get(field, getattr(instance, field)))
        validated_data["skills"] = capability_values
        return super().update(instance, validated_data)

    def get_capability_count(self, obj):
        return sum(
            len(getattr(obj, field) or [])
            for field in CAPABILITY_LIMITS
        )

    def get_runtime(self, obj):
        return runtime_snapshot(obj)

    def get_execution(self, obj):
        return worker_execution_snapshot(obj)

    def get_onboarding(self, obj):
        runtime = runtime_snapshot(obj)
        checks = {
            "identity": obj.status != WorkerAgent.Status.SETUP_REQUIRED,
            "runtime": runtime["connected"],
            "wallet": bool(obj.worker_wallet_address),
            "worker_authorisation": obj.contract_authorised,
            "capabilities": bool(obj.skills),
            "qualification": obj.test_assignment_passed,
        }
        ordered = [
            "identity",
            "runtime",
            "wallet",
            "worker_authorisation",
            "capabilities",
            "qualification",
        ]
        first_incomplete = next((name for name in ordered if not checks[name]), None)
        return {
            "checks": checks,
            "current_step": first_incomplete or "complete",
            "ready_for_activation": all(checks.values()),
        }
