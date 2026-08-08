import { StatusBadge } from "@/components/dashboard/status-badge";
import type { AgentStatus } from "@/types/veyra";

/**
 * Agent statuses share the dashboard status badge with jobs.
 *
 * The several distinct failure statuses all collapse to one "Needs attention"
 * label in the shared map: an owner only needs to know the agent is not
 * working, and the agent detail page explains why.
 */
export function AgentStatusBadge({ status }: { status: AgentStatus }) {
  return <StatusBadge status={status} />;
}
