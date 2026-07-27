import { Badge } from "@/components/ui/badge";

const labels: Record<string, string> = {
  DRAFT: "Draft",
  READY: "Ready",
  LOCKED: "Ready to Fund",
  FUNDING: "Funding",
  FUNDED: "Open",
  OPEN: "Open",
  AGENT_WORKING: "Agent Working",
  UNDER_REVIEW: "Under Review",
  COMPLETED: "Completed",
  REFUNDED: "Refunded",
  REFUND_AVAILABLE: "Refund Available",
  CANCELLED: "Cancelled",
};

const classNames: Record<string, string> = {
  OPEN: "border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-950/40 dark:text-blue-300",
  FUNDED: "border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-950/40 dark:text-blue-300",
  AGENT_WORKING: "border-yellow-200 bg-yellow-50 text-yellow-700 dark:border-yellow-800 dark:bg-yellow-950/40 dark:text-yellow-300",
  UNDER_REVIEW: "border-purple-200 bg-purple-50 text-purple-700 dark:border-purple-800 dark:bg-purple-950/40 dark:text-purple-300",
  COMPLETED: "border-green-200 bg-green-50 text-green-700 dark:border-green-800 dark:bg-green-950/40 dark:text-green-300",
  REFUNDED: "border-green-200 bg-green-50 text-green-700 dark:border-green-800 dark:bg-green-950/40 dark:text-green-300",
  REFUND_AVAILABLE: "border-orange-200 bg-orange-50 text-orange-700 dark:border-orange-800 dark:bg-orange-950/40 dark:text-orange-300",
  CANCELLED: "border-gray-200 bg-gray-50 text-gray-700 dark:border-gray-800 dark:bg-gray-950/40 dark:text-gray-300",
  DRAFT: "border-gray-200 bg-gray-50 text-gray-700 dark:border-gray-800 dark:bg-gray-950/40 dark:text-gray-300",
  READY: "border-primary-200 bg-primary-50 text-primary-700 dark:border-primary-800 dark:bg-primary-950/40 dark:text-primary-300",
  LOCKED: "border-primary-200 bg-primary-50 text-primary-700 dark:border-primary-800 dark:bg-primary-950/40 dark:text-primary-300",
  FUNDING: "border-primary-200 bg-primary-50 text-primary-700 dark:border-primary-800 dark:bg-primary-950/40 dark:text-primary-300",
};

export function JobStatusBadge({ status }: { status: string }) {
  return (
    <Badge variant="outline" className={classNames[status] ?? classNames.DRAFT}>
      {labels[status] ?? status.replaceAll("_", " ")}
    </Badge>
  );
}
