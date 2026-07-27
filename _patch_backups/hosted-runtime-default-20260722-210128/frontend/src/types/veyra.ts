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
  validation_command_detection?: {
    status: "CONFIRMED" | "SUGGESTED" | "NEEDS_CONFIRMATION";
    commands: string[];
    source?: string;
  };
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
};

export type JobDraft = {
  id: string;
  status: "DRAFT" | "READY" | "LOCKED" | "FUNDING" | "FUNDED" | "ARCHIVED";
  github_issue_url: string;
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

export type JobDetail = JobSummary & {
  acceptance_criteria: string[];
  repository: string;
  issue_number: number;
  pull_request_number: number;
  commit_hash: string;
  report_hash: string;
  evidence_hash: string;
  onchain: Record<string, unknown> | null;
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

export type AgentRuntime = {
  status: AgentRuntimeStatus;
  paired: boolean;
  connected: boolean;
  runner_id: string | null;
  runner_name: string;
  runner_version: string;
  os_name: string;
  os_version: string;
  architecture: string;
  python_version: string;
  last_seen_at: string | null;
  health_message: string;
  tools: Record<string, string>;
};

export type RuntimePairingCodeResponse = {
  pairing_code: string;
  expires_at: string;
  agent: {
    id: string;
    name: string;
  };
  instructions: string;
};

export type AgentOnboarding = {
  checks: {
    identity: boolean;
    runtime: boolean;
    github: boolean;
    wallet: boolean;
    worker_authorisation: boolean;
    capabilities: boolean;
    qualification: boolean;
  };
  current_step:
    | "identity"
    | "runtime"
    | "github"
    | "wallet"
    | "worker_authorisation"
    | "capabilities"
    | "qualification"
    | "review";
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
  worker_wallet_address: string;
  wallet_blockchain: string;
  wallet_account_type: string;
  github_username: string;
  github_connected: boolean;
  contract_authorised: boolean;
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

export type CreateAgentPayload = {
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
