import { Badge } from "@/components/ui/badge";
import type { AgentStatus } from "@/types/veyra";

const labels: Record<AgentStatus, string> = {
  SETUP_REQUIRED: "Setup required",
  PROFILE_READY: "Profile ready",
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

export function AgentStatusBadge({ status }: { status: AgentStatus }) {
  const variant =
    status === "ACTIVE"
      ? "success"
      : status === "SUSPENDED"
        ? "destructive"
        : status === "AUTHORISATION_PENDING" || status === "TESTING"
          ? "warning"
          : "secondary";

  return <Badge variant={variant}>{labels[status]}</Badge>;
}
