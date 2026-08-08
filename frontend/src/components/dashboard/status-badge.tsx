import { cn } from "@/lib/utils";

/**
 * The single status vocabulary for both dashboards.
 *
 * Every status in the application maps onto one of a small number of tones,
 * so a publisher and an agent owner reading the same job see the same
 * colour for the same state. Tones are muted on purpose: a status is
 * information, not decoration.
 */
type Tone =
  | "sand"
  | "progress"
  | "pending"
  | "success"
  | "danger"
  | "neutral"
  | "paused";

const TONE_CLASS: Record<Tone, string> = {
  // Open work: the brand accent, used sparingly and only here.
  sand: "border-primary/30 bg-primary/10 text-primary",
  progress: "border-sky-400/25 bg-sky-400/10 text-sky-300",
  pending: "border-amber-400/25 bg-amber-400/10 text-amber-300",
  success: "border-emerald-400/25 bg-emerald-400/10 text-emerald-300",
  danger: "border-red-400/25 bg-red-400/10 text-red-300",
  neutral: "border-border bg-muted/50 text-muted-foreground",
  paused: "border-border bg-muted/40 text-muted-foreground",
};

/**
 * Status values are the real ones emitted by the backend. Anything not
 * listed falls back to neutral with a humanised label, so an unmapped
 * status degrades quietly instead of breaking the row.
 */
const STATUS: Record<string, { label: string; tone: Tone }> = {
  // Job lifecycle
  DRAFT: { label: "Draft", tone: "neutral" },
  READY: { label: "Ready", tone: "neutral" },
  LOCKED: { label: "Ready to Fund", tone: "pending" },
  FUNDING: { label: "Funding", tone: "pending" },
  FUNDED: { label: "Open", tone: "sand" },
  OPEN: { label: "Open", tone: "sand" },
  CLAIMED: { label: "Claimed", tone: "progress" },
  IN_PROGRESS: { label: "In Progress", tone: "progress" },
  AGENT_WORKING: { label: "In Progress", tone: "progress" },
  SUBMITTED: { label: "Awaiting Verification", tone: "pending" },
  VERIFYING: { label: "Awaiting Verification", tone: "pending" },
  AWAITING_VERIFICATION: { label: "Awaiting Verification", tone: "pending" },
  UNDER_REVIEW: { label: "Under Review", tone: "pending" },
  COMPLETED: { label: "Completed", tone: "success" },
  SETTLED: { label: "Settled", tone: "success" },
  REFUNDED: { label: "Refunded", tone: "success" },
  REFUND_AVAILABLE: { label: "Refund Available", tone: "pending" },
  REJECTED: { label: "Rejected", tone: "danger" },
  FAILED: { label: "Failed", tone: "danger" },
  EXPIRED: { label: "Expired", tone: "danger" },
  CANCELLED: { label: "Cancelled", tone: "neutral" },

  // Agent lifecycle
  ACTIVE: { label: "Active", tone: "success" },
  PAUSED: { label: "Paused", tone: "paused" },
  SUSPENDED: { label: "Suspended", tone: "danger" },
  OFFLINE: { label: "Offline", tone: "neutral" },
  PENDING: { label: "Pending", tone: "pending" },
  CONNECTING: { label: "Connecting", tone: "progress" },
  CONNECTION_FAILED: { label: "Needs attention", tone: "danger" },
  PROVIDER_UNAVAILABLE: { label: "Needs attention", tone: "danger" },
  RUNTIME_VERIFICATION_FAILED: { label: "Needs attention", tone: "danger" },
  WALLET_CREATION_FAILED: { label: "Needs attention", tone: "danger" },
  CONTRACT_AUTHORISATION_FAILED: { label: "Needs attention", tone: "danger" },
};

function humanise(status: string) {
  return status
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function StatusBadge({
  status,
  className,
}: {
  status: string;
  className?: string;
}) {
  const key = status?.toUpperCase() ?? "";
  const entry = STATUS[key];
  const tone = entry?.tone ?? "neutral";

  return (
    <span
      className={cn(
        "inline-flex items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium",
        TONE_CLASS[tone],
        className,
      )}
    >
      {entry?.label ?? humanise(status ?? "Unknown")}
    </span>
  );
}
