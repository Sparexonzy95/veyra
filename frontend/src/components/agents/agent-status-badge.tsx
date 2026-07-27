import { Badge } from "@/components/ui/badge";
import type { AgentStatus } from "@/types/veyra";

const labels: Record<AgentStatus, string> = {
  SETUP_REQUIRED: "Setup required",
  PROFILE_READY: "Profile ready",
  PROVISIONING: "Provisioning",
  RUNTIME_CONNECTED: "Runtime connected",
  READY_FOR_QUALIFICATION: "Ready for qualification",
  RUNTIME_VERIFICATION_FAILED: "Runtime verification failed",
  WALLET_CREATION_FAILED: "Wallet creation failed",
  CONTRACT_AUTHORISATION_FAILED: "Contract authorisation failed",
  PROVIDER_UNAVAILABLE: "Provider unavailable",
  CONNECTION_FAILED: "Connection failed",
  ENGINE_CONNECTED: "Runtime ready",
  WALLET_READY: "Wallet ready",
  PAYOUT_READY: "Payout ready",
  GITHUB_READY: "GitHub ready",
  AUTHORISATION_PENDING: "Authorisation pending",
  TESTING: "Readiness running",
  ACTIVE: "Active",
  PAUSED: "Paused",
  SUSPENDED: "Suspended",
};

const failureStatuses: AgentStatus[] = [
  "RUNTIME_VERIFICATION_FAILED",
  "WALLET_CREATION_FAILED",
  "CONTRACT_AUTHORISATION_FAILED",
  "PROVIDER_UNAVAILABLE",
  "CONNECTION_FAILED",
  "SUSPENDED",
];

export function AgentStatusBadge({ status }: { status: AgentStatus }) {
  const variant =
    status === "ACTIVE" || status === "READY_FOR_QUALIFICATION"
      ? "success"
      : failureStatuses.includes(status)
        ? "destructive"
        : status === "AUTHORISATION_PENDING" || status === "TESTING" || status === "PROVISIONING"
          ? "warning"
          : "secondary";

  return <Badge variant={variant}>{labels[status]}</Badge>;
}
