export type UserSummary = {
  id: string;
  display_name: string;
  email: string;
};

export type WalletSummary = {
  address: string;
  blockchain: string;
  account_type?: string;
  status?: string;
  usdc_balance?: string;
  last_balance_sync_at?: string | null;
};

export type MeResponse = {
  authenticated: boolean;
  onboarding?: boolean;
  requires_wallet_setup?: boolean;
  user?: UserSummary;
  capabilities?: string[];
  wallet?: WalletSummary | null;
};

export type CircleSession = {
  authMethod: "GOOGLE" | "EMAIL";
  email?: string;
  displayName?: string;
  encryptionKey: string;
  refreshToken?: string;
  userToken: string;
  circleUserId?: string;
};


export type GitHubInstallationState =
  | "CONNECTED"
  | "CHECKING"
  | "LIMITED_ACCESS"
  | "CREDENTIAL_GENERATION_FAILED"
  | "SUSPENDED"
  | "RECONNECT_REQUIRED"
  | "DISCONNECTED";

export type GitHubAppInstallation = {
  id: string;
  installation_id: number;
  account_login: string;
  account_type: string;
  repository_selection: string;
  permissions: Record<string, string>;
  status: GitHubInstallationState;
  last_checked_at: string | null;
  last_error: string;
};

export type GitHubRepositoryAccess = {
  id: string;
  installation_id: string;
  github_repository_id: number;
  owner: string;
  name: string;
  full_name: string;
  private: boolean;
  default_branch: string;
  html_url: string;
  permissions: Record<string, boolean>;
  active: boolean;
  last_synced_at: string | null;
};

export type GitHubConnectionStatus = {
  configured: boolean;
  app_slug: string;
  connected: boolean;
  connection_state: GitHubInstallationState;
  installations: GitHubAppInstallation[];
  repositories: GitHubRepositoryAccess[];
};

export type GitHubIssueListItem = {
  number: number;
  title: string;
  state: string;
  html_url: string;
  updated_at: string;
  author_login: string;
  labels: string[];
};

export type GitHubRepositoryIssueList = {
  repository: GitHubRepositoryAccess;
  issues: GitHubIssueListItem[];
};

export type RepositoryStackItem = {
  name: string;
  category:
    | "language"
    | "runtime"
    | "framework"
    | "database"
    | "testing"
    | "styling"
    | "infrastructure"
    | "package_manager"
    | string;
  version?: string;
  source?: string;
};

export type TechnicalRequirement = {
  name: string;
  version?: string;
  category?: string;
  level: "REQUIRED" | "PREFERRED";
};

export type VerificationMethod =
  | "AUTOMATED_TEST"
  | "TEST_SUITE"
  | "FILE_INSPECTION"
  | "PULL_REQUEST_INSPECTION"
  | "MANUAL_REVIEW";

export type GitHubIssuePreview = {
  github_issue_url: string;
  repository_owner: string;
  repository_name: string;
  repository_visibility?: string;
  repository_description?: string;
  target_branch: string;
  issue_number: number;
  issue_title: string;
  issue_body: string;
  issue_state?: string;
  acceptance_criteria: string[];
  repository_stack?: RepositoryStackItem[];
  suggested_allowed_paths?: string[];
  suggested_required_commands?: string[];
  github_repository_access_id?: string;
  github_installation_status?: GitHubInstallationState;
  validation_command_detection?: {
    status: "CONFIRMED" | "SUGGESTED" | "NEEDS_CONFIRMATION";
    commands: string[];
    source?: string;
  };
};

export type GitHubCiPreflight = {
  repository_id: string;
  repository: string;
  branch: string;
  ready: boolean;
  checks_permission: boolean;
  workflow_files: string[];
  automatic_workflows: string[];
  recent_check_runs: Array<{
    name: string;
    status: string;
    conclusion: string;
    app: string;
  }>;
  source:
    | "AUTOMATIC_WORKFLOW"
    | "EXISTING_CHECK_PROVIDER"
    | "WORKFLOW_NOT_AUTOMATIC"
    | "NO_CI_EVIDENCE"
    | "MISSING_CHECKS_PERMISSION";
  message: string;
};

export type JobAdvancedOptions = {
  job_title?: string;
  job_type?: string;
  job_description?: string;
  repository_stack?: RepositoryStackItem[];
  technical_requirements?: TechnicalRequirement[];
  criterion_verification_methods?: VerificationMethod[];
  invited_provider_address?: string;
  allowed_paths?: string[];
  forbidden_paths?: string[];
  required_commands?: string[];
  delivery_type?: "PULL_REQUEST" | "COMMIT";
  require_github_checks?: boolean;
};

export type JobDraft = {
  id: string;
  status: "DRAFT" | "READY" | "LOCKED" | "FUNDING" | "FUNDED" | "ARCHIVED";
  github_issue_url: string;
  github_repository_access?: string | null;
  github_repository?: {
    id: string;
    full_name: string;
    private: boolean;
    default_branch: string;
    active: boolean;
    installation_status: GitHubInstallationState;
  } | null;
  repository_owner: string;
  repository_name: string;
  target_branch: string;
  issue_number: number;
  issue_title: string;
  issue_body: string;
  budget_usdc: string;
  deadline: string;
  acceptance_criteria: string[];
  advanced_options: JobAdvancedOptions;
  created_at: string;
  updated_at: string;
};

export type JobSummary = {
  onchain_job_id: number;
  title: string;
  github_issue_url: string;
  client_status: string;
  status: string;
  budget_usdc: string;
  provider_address: string;
  expires_at: number;
  updated_at: string;
};


export type RuntimeProgress = {
  assignment_id: string;
  job_id?: string;
  status: string;
  phase: string;
  message: string;
  updated_at: string;
};

export type ExecutionAssignment = {
  id: string;
  job_id: number;
  job_title: string;
  status: string;
  stage_label: string;
  assignment_attempt: number;
  candidate_count: number;
  matching_score: number;
  fairness_rank: number;
  selection_reason: string;
  agent: {
    id: string;
    name: string;
    slug: string;
    wallet_address: string;
  };
  runtime: {
    status: string;
    connected: boolean;
    provider_ready: boolean;
    last_seen_at: string | null;
    health_message: string;
    progress: RuntimeProgress | null;
  };
  runtime_last_seen_at: string | null;
  attention_required: boolean;
  attention_code: string;
  attention_message: string;
  repository: string;
  issue_number: number;
  reserved_at: string | null;
  reserved_until: string | null;
  leased_at: string | null;
  lease_expires_at: string | null;
  execution_started_at: string | null;
  execution_completed_at: string | null;
  branch: string;
  commit_sha: string;
  pull_request_number: number | null;
  pull_request_url: string;
  changed_files: string[];
  baseline_tests_passed: boolean | null;
  post_change_tests_passed: boolean;
  claim_transaction_hash: string;
  submission_transaction_hash: string;
  verification_status: string;
  verification_report_hash: string;
  verification_evidence_hash: string;
  independent_verifier: {
    id: string;
    status: string;
    verdict: string;
    assignment_attempt: number;
    candidate_count: number;
    matching_score: number;
    fairness_rank: number;
    selection_reason: string;
    agent: {
      id: string;
      name: string;
      slug: string;
    };
    leased_at: string | null;
    lease_expires_at: string | null;
    started_at: string | null;
    completed_at: string | null;
    report_hash: string;
    evidence_hash: string;
    summary: string;
    failure_message: string;
    progress: RuntimeProgress | null;
  } | null;
  settlement_transaction_hash: string;
  settlement_confirmed_at: string | null;
  failure_stage: string;
  failure_message: string;
  retryable: boolean;
  failure_history: Array<{
    source: string;
    stage: string;
    message: string;
    recovered_at: string | null;
  }>;
  created_at: string | null;
  updated_at: string | null;
};

export type JobExecution = {
  automatic: boolean;
  assignment: ExecutionAssignment | null;
  matching_status:
    | "IDLE"
    | "MATCHING"
    | "RETRYING"
    | "NO_ELIGIBLE_AGENT"
    | "PAUSED"
    | "ASSIGNED";
  matching_reason_code: string;
  matching_next_retry_at: string | null;
  controller: {
    online: boolean;
    last_cycle_started_at: string | null;
    last_cycle_finished_at: string | null;
    next_cycle_at: string | null;
    consecutive_failures: number;
    last_error_code: string;
    last_error_message: string;
  };
  message: string;
};

export type AgentExecution = {
  auto_claim_enabled: boolean;
  discovery_enabled: boolean;
  active_jobs: number;
  capacity: number;
  current_assignment: ExecutionAssignment | null;
  recent_assignments: Array<ExecutionAssignment | null>;
  reputation: {
    karma_score: number;
    completed_jobs: number;
    failed_jobs: number;
    abandoned_jobs: number;
    total_earned_atomic: string;
    total_earned_usdc: string;
    synced_at: string | null;
  };
};

export type JobDetail = JobSummary & {
  acceptance_criteria: string[];
  repository: string;
  issue_number: number;
  pull_request_number: number;
  commit_hash: string;
  report_hash: string;
  evidence_hash: string;
  onchain: Record<string, unknown> | null;
  execution: JobExecution;
  verification_requirements: {
    veyra_independent_verification: boolean;
    funded_validation: boolean;
    github_ci_required: boolean;
  };
  available_action: {
    code: "CANCEL_JOB" | "CLAIM_REFUND";
    contract_function: string;
    label: string;
  } | null;
};

export type NotificationItem = {
  id: string;
  event_type: string;
  title: string;
  body: string;
  resource_type: string;
  resource_id: string;
  read_at: string | null;
  created_at: string;
};

export type DashboardResponse = {
  wallet: WalletSummary | null;
  job_counts: Record<string, number>;
  jobs: JobSummary[];
  notifications: NotificationItem[];
};

export type CircleTransactionState =
  | "CREATED"
  | "CHALLENGE_READY"
  | "USER_APPROVAL_PENDING"
  | "SUBMITTED"
  | "PENDING_ONCHAIN"
  | "CONFIRMED"
  | "DENIED"
  | "FAILED"
  | "EXPIRED"
  | "EVENT_MISMATCH";

export type CircleTransactionStatus = {
  id: string;
  purpose: "USDC_APPROVAL" | "JOB_CREATE" | "JOB_CANCEL" | "JOB_REFUND" | string;
  status: CircleTransactionState;
  challenge_id?: string | null;
  circle_transaction_id?: string | null;
  arc_transaction_hash?: string;
  contract_address?: string;
  draft_id?: string | null;
  job_id?: number | null;
  block_number?: number | null;
  gas_used?: number | null;
  failure_code?: string;
  failure_message?: string;
  event_payload?: Record<string, unknown>;
  submitted_at?: string | null;
  confirmed_at?: string | null;
  created_at: string;
  updated_at: string;
  terminal: boolean;
};

export type CircleChallengeResponse = {
  challenge_id?: string | null;
  transaction_id?: string;
  transaction_status?: CircleTransactionState;
  requires_user_approval?: boolean;
  reused?: boolean;
};

export type AgentSpecialisation =
  | "PYTHON_BACKEND"
  | "JAVASCRIPT_FRONTEND"
  | "FULL_STACK_WEB"
  | "SMART_CONTRACT"
  | "TESTING_QA"
  | "DOCUMENTATION";

export type AgentStatus =
  | "SETUP_REQUIRED"
  | "PROFILE_READY"
  | "PROVISIONING"
  | "RUNTIME_CONNECTED"
  | "READY_FOR_QUALIFICATION"
  | "RUNTIME_VERIFICATION_FAILED"
  | "WALLET_CREATION_FAILED"
  | "CONTRACT_AUTHORISATION_FAILED"
  | "PROVIDER_UNAVAILABLE"
  | "CONNECTION_FAILED"
  | "ENGINE_CONNECTED"
  | "WALLET_READY"
  | "PAYOUT_READY"
  | "GITHUB_READY"
  | "AUTHORISATION_PENDING"
  | "TESTING"
  | "ACTIVE"
  | "PAUSED"
  | "SUSPENDED";


export type AgentRuntimeStatus =
  | "NOT_CONNECTED"
  | "PAIRED"
  | "ONLINE"
  | "OFFLINE"
  | "UNHEALTHY"
  | "REVOKED";

export type AgentRuntimeMode = "VEYRA_HOSTED" | "OWNER_HOSTED";

export type AgentRuntime = {
  status: AgentRuntimeStatus;
  paired: boolean;
  connected: boolean;
  runtime_mode: AgentRuntimeMode;
  managed_by: "VEYRA" | "OWNER";
  auto_start: boolean;
  runner_id: string | null;
  runner_name: string;
  runner_version: string;
  os_name: string;
  os_version: string;
  architecture: string;
  python_version: string;
  last_seen_at: string | null;
  provisioned_at: string | null;
  health_message: string;
  tools: Record<string, unknown>;
  provider: string;
  model: string;
  provider_ready: boolean;
  protocol_version: number | null;
  public_key_fingerprint: string;
  connection_method: "COPY_LINK_V1" | "LEGACY_PAIRING";
};

export type AgentOnboarding = {
  checks: {
    identity: boolean;
    runtime: boolean;
    wallet: boolean;
    worker_authorisation: boolean;
    capabilities: boolean;
    qualification: boolean;
  };
  current_step:
    | "identity"
    | "runtime"
    | "wallet"
    | "worker_authorisation"
    | "capabilities"
    | "qualification"
    | "review"
    | "complete";
  ready_for_activation: boolean;
};

export type AgentSummary = {
  id: string;
  slug: string;
  name: string;
  description: string;
  avatar_url: string;
  status: AgentStatus;
  specialisation: AgentSpecialisation;
  languages: string[];
  frameworks: string[];
  testing_tools: string[];
  task_types: string[];
  capability_count: number;
  minimum_budget_usdc: string;
  maximum_budget_usdc: string;
  public_repositories_only: boolean;
  allowed_organizations: string[];
  auto_claim_enabled: boolean;
  maximum_active_jobs: number;
  maximum_execution_minutes: number;
  allow_fork_creation: boolean;
  allow_new_dependencies: boolean;
  allow_database_migrations: boolean;
  protected_paths: string[];
  engine_connected: boolean;
  engine_version: string;
  engine_last_checked_at: string | null;
  engine_last_error: string;
  runtime: AgentRuntime;
  execution: AgentExecution;
  worker_wallet_address: string;
  wallet_blockchain: string;
  wallet_account_type: string;
  github_username: string;
  github_connected: boolean;
  contract_authorised: boolean;
  contract_authorisation_tx_hash: string;
  provisioning_stage: string;
  provisioning_error: string;
  test_assignment_passed: boolean;
  discovery_enabled: boolean;
  activated_at: string | null;
  onboarding: AgentOnboarding;
  created_at: string;
  updated_at: string;
};

export type PaginatedAgents = {
  count: number;
  next: string | null;
  previous: string | null;
  results: AgentSummary[];
};

export type AgentWalletProvisionResponse = {
  wallet: {
    address: string;
    blockchain: string;
    account_type: string;
    created: boolean;
  };
  agent: AgentSummary;
};

export type CreateAgentPayload = {
  connection_link: string;
  name: string;
  description: string;
  avatar_url?: string;
  specialisation: AgentSpecialisation;
  languages: string[];
  frameworks: string[];
  testing_tools: string[];
  task_types: string[];
  minimum_budget_usdc: string;
  maximum_budget_usdc: string;
  public_repositories_only: boolean;
  allowed_organizations: string[];
  maximum_active_jobs: number;
  maximum_execution_minutes: number;
  allow_fork_creation: boolean;
  allow_new_dependencies: boolean;
  allow_database_migrations: boolean;
  protected_paths: string[];
};
