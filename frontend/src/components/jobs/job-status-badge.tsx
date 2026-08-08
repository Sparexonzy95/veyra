import { StatusBadge } from "@/components/dashboard/status-badge";

/**
 * Job statuses now render through the shared dashboard status badge so a job
 * looks identical wherever it appears, on client pages and agent pages alike.
 * The label and tone mapping lives in one place: components/dashboard/status-badge.
 */
export function JobStatusBadge({ status }: { status: string }) {
  return <StatusBadge status={status} />;
}
