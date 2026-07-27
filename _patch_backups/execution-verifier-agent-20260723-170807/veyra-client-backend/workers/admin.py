from django.contrib import admin

from workers.models import (
    HostedAgentConnection,
    RunnerAgentBinding,
    RunnerDevice,
    RunnerPairingCode,
    WorkerAgent,
    WorkerJobQueueItem,
    WorkerQualificationRun,
    WorkerTestAssignment,
)


@admin.register(WorkerAgent)
class WorkerAgentAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "status",
        "owner_type",
        "engine_provider",
        "engine_connected",
        "engine_version",
        "github_username",
        "wallet_blockchain",
        "contract_authorised",
        "test_assignment_passed",
        "discovery_enabled",
    )
    list_filter = (
        "status",
        "owner_type",
        "engine_provider",
        "engine_connected",
        "contract_authorised",
        "test_assignment_passed",
        "github_connected",
        "discovery_enabled",
    )
    search_fields = (
        "name",
        "slug",
        "github_username",
        "worker_wallet_address",
        "engine_model",
        "engine_version",
    )
    readonly_fields = (
        "id",
        "engine_connected",
        "engine_version",
        "engine_last_checked_at",
        "engine_last_error",
        "engine_connection_metadata",
        "circle_wallet_id",
        "circle_wallet_set_id",
        "worker_wallet_address",
        "activated_at",
        "created_at",
        "updated_at",
    )


@admin.register(HostedAgentConnection)
class HostedAgentConnectionAdmin(admin.ModelAdmin):
    list_display = (
        "worker",
        "runtime_id",
        "status",
        "provider",
        "model_name",
        "provider_ready",
        "last_seen_at",
    )
    list_filter = ("status", "provider", "provider_ready", "protocol_version")
    search_fields = ("worker__name", "runtime_id", "runtime_url", "model_name")
    readonly_fields = (
        "id",
        "worker",
        "runtime_id",
        "runtime_url",
        "public_key",
        "public_key_fingerprint",
        "protocol_version",
        "runtime_version",
        "provider",
        "model_name",
        "provider_ready",
        "capabilities",
        "credential_hash",
        "status",
        "connected_at",
        "last_seen_at",
        "revoked_at",
        "last_error",
        "metadata",
        "created_at",
        "updated_at",
    )


@admin.register(RunnerDevice)
class RunnerDeviceAdmin(admin.ModelAdmin):
    list_display = ("name", "owner_user", "status", "health", "runner_version", "last_seen_at")
    list_filter = ("status", "health", "os_name")
    search_fields = ("name", "owner_user__handle", "device_address")
    readonly_fields = ("id", "device_address", "last_seen_at", "created_at", "updated_at")


@admin.register(RunnerAgentBinding)
class RunnerAgentBindingAdmin(admin.ModelAdmin):
    list_display = ("worker", "runner", "status", "paired_at", "revoked_at")
    list_filter = ("status",)
    search_fields = ("worker__name", "runner__name", "runner__owner_user__handle")
    readonly_fields = ("id", "paired_at", "created_at", "updated_at")


@admin.register(RunnerPairingCode)
class RunnerPairingCodeAdmin(admin.ModelAdmin):
    list_display = ("worker", "owner_user", "expires_at", "consumed_at", "cancelled_at")
    search_fields = ("worker__name", "owner_user__handle")
    readonly_fields = (
        "id",
        "worker",
        "owner_user",
        "code_hash",
        "expires_at",
        "consumed_at",
        "cancelled_at",
        "created_at",
        "updated_at",
    )


@admin.register(WorkerTestAssignment)
class WorkerTestAssignmentAdmin(admin.ModelAdmin):
    list_display = (
        "worker",
        "status",
        "source_owner",
        "source_repository",
        "issue_number",
        "post_test_passed",
        "pull_request_number",
        "created_at",
    )
    list_filter = ("status", "post_test_passed", "source_owner")
    search_fields = (
        "worker__name",
        "source_owner",
        "source_repository",
        "issue_title",
        "commit_sha",
        "pull_request_url",
    )
    readonly_fields = (
        "id",
        "worker",
        "status",
        "issue_url",
        "repository_url",
        "source_owner",
        "source_repository",
        "issue_number",
        "issue_title",
        "issue_body",
        "acceptance_criteria",
        "base_branch",
        "fork_owner",
        "fork_repository",
        "branch_name",
        "workspace_name",
        "baseline_test_command",
        "post_test_command",
        "baseline_test_passed",
        "post_test_passed",
        "changed_files",
        "commit_sha",
        "pull_request_number",
        "pull_request_url",
        "engine_output",
        "baseline_test_output",
        "test_output",
        "failure_stage",
        "failure_message",
        "started_at",
        "completed_at",
        "created_at",
        "updated_at",
    )


@admin.register(WorkerQualificationRun)
class WorkerQualificationRunAdmin(admin.ModelAdmin):
    list_display = (
        "worker",
        "attempt_number",
        "status",
        "provider",
        "model_name",
        "test_return_code",
        "created_at",
    )
    list_filter = ("status", "task_version", "provider")
    search_fields = ("worker__name", "worker__slug", "model_name")
    readonly_fields = (
        "id",
        "worker",
        "attempt_number",
        "task_version",
        "status",
        "lease_expires_at",
        "started_at",
        "submitted_at",
        "completed_at",
        "provider",
        "model_name",
        "runtime_version",
        "submitted_files",
        "test_return_code",
        "test_output",
        "result_signature",
        "failure_message",
        "created_at",
        "updated_at",
    )


@admin.register(WorkerJobQueueItem)
class WorkerJobQueueItemAdmin(admin.ModelAdmin):
    list_display = (
        "worker",
        "job",
        "status",
        "eligibility_code",
        "priority_score",
        "onchain_status",
        "github_freshness_code",
        "claim_circle_state",
        "execution_post_test_passed",
        "execution_pull_request_number",
        "submission_circle_state",
        "source",
        "last_checked_at",
    )
    list_filter = ("status", "eligibility_passed", "source", "onchain_status")
    search_fields = (
        "worker__name",
        "worker__slug",
        "job__onchain_job_id",
        "job__draft__repository_owner",
        "job__draft__repository_name",
        "eligibility_code",
    )
    readonly_fields = (
        "id",
        "worker",
        "job",
        "status",
        "source",
        "eligibility_passed",
        "eligibility_code",
        "eligibility_detail",
        "priority_score",
        "required_skills",
        "matched_skills",
        "onchain_status",
        "onchain_snapshot",
        "github_freshness_code",
        "github_snapshot",
        "github_last_checked_at",
        "last_checked_at",
        "queued_at",
        "claim_idempotency_key",
        "claim_attempt_count",
        "claim_circle_transaction_id",
        "claim_circle_state",
        "claim_arc_transaction_hash",
        "claim_receipt_block_number",
        "claim_failure_stage",
        "claim_failure_message",
        "claim_started_at",
        "claim_submitted_at",
        "claim_last_checked_at",
        "claim_confirmed_at",
        "execution_attempt_count",
        "execution_branch_name",
        "execution_workspace_name",
        "execution_baseline_test_command",
        "execution_post_test_command",
        "execution_baseline_test_passed",
        "execution_post_test_passed",
        "execution_changed_files",
        "execution_commit_sha",
        "execution_pull_request_number",
        "execution_pull_request_url",
        "execution_engine_output",
        "execution_baseline_test_output",
        "execution_test_output",
        "execution_failure_stage",
        "execution_failure_message",
        "execution_started_at",
        "execution_completed_at",
        "submission_idempotency_key",
        "submission_attempt_count",
        "submission_commit_hash",
        "submission_deliverable_hash",
        "submission_circle_transaction_id",
        "submission_circle_state",
        "submission_arc_transaction_hash",
        "submission_receipt_block_number",
        "submission_failure_stage",
        "submission_failure_message",
        "submission_started_at",
        "submission_submitted_at",
        "submission_last_checked_at",
        "submission_confirmed_at",
        "created_at",
        "updated_at",
    )
