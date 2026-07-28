import { Badge } from "@/components/ui/badge";
import type { AgentStatus } from "@/types/veyra";

const attentionStatuses: AgentStatus[] = [
  "RUNTIME_VERIFICATION_FAILED",
  "WALLET_CREATION_FAILED",
  "CONTRACT_AUTHORISATION_FAILED",
  "PROVIDER_UNAVAILABLE",
  "CONNECTION_FAILED",
  "SUSPENDED",
];

export function AgentStatusBadge({ status }: { status: AgentStatus }) {
  if (status === "ACTIVE") {
    return <Badge variant="success">Active</Badge>;
  }
  if (attentionStatuses.includes(status)) {
    return <Badge variant="destructive">Needs attention</Badge>;
  }
  return <Badge variant="secondary">Offline</Badge>;
}
