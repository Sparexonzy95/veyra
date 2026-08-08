"use client";

import { JobStatusBadge } from "@/components/jobs/job-status-badge";
import { useVeyra } from "@/components/providers/veyra-provider";
import { Button } from "@/components/ui/button";
import { apiFetch, postJson } from "@/lib/api";
import type { CircleChallengeResponse, JobDetail } from "@/types/veyra";
import {
  ArrowLeft,
  Check,
  ExternalLink,
  GitPullRequest,
  Loader2,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

const steps = ["OPEN", "AGENT_WORKING", "UNDER_REVIEW", "COMPLETED"] as const;
const stepLabels = ["Open", "Agent working", "Review", "Completed"];

/** States where a four-step timeline would misdescribe what happened. */
const ENDED_EARLY = ["REFUNDED", "CANCELLED"];

/**
 * Client job detail.
 *
 * Layout: compact header, three summary facts, an inline timeline, then two
 * columns — the task and its acceptance checklist on the left, a single Work
 * summary on the right. Everything an engineer needs and a publisher does
 * not (hashes, IDs, contract status, retry bookkeeping) sits in one closed
 * `Technical details` block at the end.
 *
 * Surfaces are drawn directly here rather than with Panel/PanelHeader
 * because Panel adds a bordered header strip per section; at this density
 * that produced a stack of nested boxes, which is what the redesign is
 * meant to remove. Colours are all semantic tokens (`card`, `border`,
 * `foreground`, `muted-foreground`), so the near-black/graphite/cream
 * palette comes from the theme rather than from hardcoded values here.
 */
export default function JobDetailPage() {
  const params = useParams<{ id: string }>();
  const { circleToken, executeTrackedChallenge } = useVeyra();

  const [job, setJob] = useState<JobDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [retryLoading, setRetryLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true);
      setError(null);
      try {
        setJob(await apiFetch<JobDetail>(`/api/v1/client/jobs/${params.id}/`));
      } catch (loadError) {
        setError(
          loadError instanceof Error
            ? loadError.message
            : "Job could not be loaded.",
        );
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [params.id],
  );

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (job?.client_status === "COMPLETED" || ENDED_EARLY.includes(job?.client_status || "")) {
      return;
    }
    const interval = window.setInterval(() => void load(true), 2000);
    return () => window.clearInterval(interval);
  }, [job?.client_status, load]);

  const activeIndex = useMemo(() => {
    if (!job) return 0;
    return Math.max(0, steps.indexOf(job.client_status as (typeof steps)[number]));
  }, [job]);

  async function performAction() {
    if (!job?.available_action || !circleToken) {
      toast.error("Reconnect your secure wallet to continue.");
      return;
    }
    setActionLoading(true);
    try {
      const challenge = await postJson<
        CircleChallengeResponse & { action: { label: string } }
      >(
        `/api/v1/client/jobs/${job.onchain_job_id}/action-challenge/`,
        {},
        circleToken,
      );
      if (!challenge.challenge_id) {
        throw new Error("Circle did not return the transaction approval request.");
      }
      await executeTrackedChallenge(challenge.challenge_id, challenge.transaction_id);
      toast.success(`${challenge.action.label} submitted to Arc.`);
      await load();
    } catch (actionError) {
      toast.error(
        actionError instanceof Error ? actionError.message : "Action failed.",
      );
    } finally {
      setActionLoading(false);
    }
  }

  async function retryExecution() {
    if (!job?.execution.assignment?.retryable || retryLoading) return;
    setRetryLoading(true);
    try {
      const result = await postJson<{ code: string; message: string }>(
        `/api/v1/client/jobs/${job.onchain_job_id}/retry-execution/`,
        {},
      );
      toast.success(result.message);
      await load(true);
    } catch (retryError) {
      toast.error(
        retryError instanceof Error
          ? retryError.message
          : "The execution retry could not be queued.",
      );
    } finally {
      setRetryLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-primary" />
      </div>
    );
  }

  if (error || !job) {
    return (
      <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
        {error ?? "Job not found."}
      </div>
    );
  }

  const assignment = job.execution.assignment;
  const verifier = assignment?.independent_verifier ?? null;
  const executionProgress = assignment?.runtime.progress ?? null;
  const verifierProgress = verifier?.progress ?? null;
  const verdict = verifier?.verdict || assignment?.verification_status || "";
  const settled = Boolean(
    assignment?.settlement_confirmed_at && job.client_status === "COMPLETED",
  );
  const settlementPending = Boolean(
    !settled &&
      (assignment?.status === "SETTLING" || assignment?.settlement_transaction_hash),
  );
  const settlementLabel = settled
    ? "Paid to agent"
    : settlementPending
      ? "Settlement pending"
      : "Held in escrow";
  const problem = assignment?.attention_message || assignment?.failure_message || "";
  const waitingForGithubCi = Boolean(
    job.verification_requirements?.github_ci_required &&
      assignment?.failure_stage === "verification_pending" &&
      problem.toLowerCase().includes("github ci"),
  );
  const canRetryExecution = Boolean(
    assignment?.status === "FAILED" && assignment.retryable,
  );
  // A timeline is only honest while the job is still walking the four steps.
  const showTimeline = !ENDED_EARLY.includes(job.client_status);
  // "Completed" already implies "Verified", so a second badge saying so is
  // noise. The verdict earns its place only when it disagrees with the
  // status badge: work rejected, or verified but not yet completed.
  const showVerdict =
    isRejected(verdict) ||
    (isApproved(verdict) && job.client_status !== "COMPLETED");
  // Hashes and wallets are the technical payload; the onchain ID and
  // contract status alone do not justify a disclosure of their own.
  const hasTechnical = Boolean(
    job.commit_hash ||
      job.report_hash ||
      job.evidence_hash ||
      assignment?.settlement_transaction_hash ||
      assignment?.agent.wallet_address,
  );

  return (
    <div className="space-y-4">
      {/* Header */}
      <div>
        <Link
          href="/client/jobs"
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to Jobs
        </Link>

        <div className="mt-2 flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-lg font-semibold tracking-tight text-foreground md:text-xl">
                {job.title}
              </h1>
              <JobStatusBadge status={job.client_status} />
              {showVerdict ? <VerdictBadge verdict={verdict} /> : null}
            </div>
            <a
              href={job.github_issue_url}
              target="_blank"
              rel="noreferrer"
              className="mt-1 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            >
              {job.repository} · Issue #{job.issue_number}
              <ExternalLink className="h-3 w-3" />
            </a>
          </div>

          {job.available_action ? (
            <Button
              size="sm"
              variant={
                job.available_action.code === "CANCEL_JOB" ? "destructive" : "default"
              }
              onClick={() => void performAction()}
              disabled={actionLoading}
              className="h-8 shrink-0"
            >
              {actionLoading ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : null}
              {job.available_action.label}
            </Button>
          ) : null}
        </div>
      </div>

      {/* Summary: three facts on one line, not four cards. */}
      <dl className="flex flex-wrap items-center gap-x-8 gap-y-2 rounded-lg border border-border bg-card px-4 py-2.5">
        <Fact label="Reward" value={`${formatUsdc(job.budget_usdc)} USDC`} />
        <Fact
          label="Deadline"
          value={new Date(job.expires_at * 1000).toLocaleDateString()}
        />
        <Fact label="Settlement" value={settlementLabel} />
      </dl>

      {problem ? (
        <div
          className={`flex flex-col gap-2 rounded-lg border px-3 py-2 text-xs sm:flex-row sm:items-center sm:justify-between ${
            waitingForGithubCi
              ? "border-amber-300 bg-amber-50/60 text-amber-900 dark:border-amber-900 dark:bg-amber-950/20 dark:text-amber-200"
              : "border-destructive/30 bg-destructive/5 text-destructive"
          }`}
        >
          <div>
            <p>{problem}</p>
            {waitingForGithubCi ? (
              <p className="mt-1 opacity-80">
                This requirement was locked when the job was funded. Veyra rechecks the exact submitted commit automatically.
              </p>
            ) : null}
          </div>
          {canRetryExecution && !waitingForGithubCi ? (
            <Button
              size="sm"
              variant="outline"
              onClick={() => void retryExecution()}
              disabled={retryLoading}
              className="h-8 shrink-0 border-destructive/40 bg-background text-foreground hover:bg-destructive/10"
            >
              {retryLoading ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : null}
              Retry execution
            </Button>
          ) : null}
        </div>
      ) : null}

      {showTimeline ? (
        <ol className="flex flex-wrap items-center gap-x-2 gap-y-1 px-0.5 text-xs">
          {steps.map((step, index) => (
            <li key={step} className="flex items-center gap-2">
              {index > 0 ? (
                <span aria-hidden className="text-muted-foreground/40">
                  ›
                </span>
              ) : null}
              <span
                className={
                  index < activeIndex
                    ? "inline-flex items-center gap-1 text-muted-foreground"
                    : index === activeIndex
                      ? "font-medium text-foreground"
                      : "text-muted-foreground/50"
                }
              >
                {index < activeIndex ? (
                  <Check className="h-3 w-3 text-primary" aria-hidden />
                ) : null}
                {stepLabels[index]}
              </span>
            </li>
          ))}
        </ol>
      ) : null}

      {/* Two columns on desktop, stacked on mobile. */}
      <div className="grid gap-4 lg:grid-cols-5">
        <div className="space-y-4 lg:col-span-3">
          {/* No "Task" panel: the client job endpoint returns no description
              field (the brief lives in the GitHub issue), so the panel could
              only repeat the title already shown in the header. The issue
              link stays in the header where the repository is. */}
          <section className="rounded-lg border border-border bg-card p-4">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Acceptance criteria
            </h2>
            {job.acceptance_criteria.length ? (
              <ul className="mt-2 space-y-1.5">
                {job.acceptance_criteria.map((criterion) => (
                  <li key={criterion} className="flex items-start gap-2 text-sm">
                    <Check
                      className="mt-[3px] h-3.5 w-3.5 shrink-0 text-primary"
                      aria-hidden
                    />
                    <span className="text-foreground">{criterion}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-sm text-muted-foreground">
                None recorded for this job.
              </p>
            )}
          </section>
        </div>

        {/* Work summary: one panel, four facts, no table rows. */}
        <section className="rounded-lg border border-border bg-card p-4 lg:col-span-2">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Work summary
          </h2>

          {assignment ? (
            <div className="mt-3 space-y-3 text-sm">
              <Item label="Agent">{assignment.agent.name}</Item>

              {assignment.status === "LEASED" || assignment.status === "EXECUTING" ? (
                <Item label="Execution">
                  <span className="inline-flex items-center gap-1.5">
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                    {executionProgress?.message || assignment.stage_label}
                  </span>
                </Item>
              ) : null}

              <Item label="Pull request">
                {assignment.pull_request_url ? (
                  <a
                    href={assignment.pull_request_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-primary hover:underline"
                  >
                    <GitPullRequest className="h-3.5 w-3.5" />#
                    {assignment.pull_request_number}
                  </a>
                ) : (
                  <span className="text-muted-foreground">Not submitted yet</span>
                )}
              </Item>

              <Item label="Verification result">
                {verdict || verifier ? (
                  <>
                    <span className="block">{verificationLine(verdict, verifier?.summary)}</span>
                    {verifierProgress?.message && !verdict ? (
                      <span className="mt-1 inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                        <Loader2 className="h-3 w-3 animate-spin text-primary" />
                        {verifierProgress.message}
                      </span>
                    ) : null}
                    {verifier ? (
                      <details className="mt-1.5">
                        <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
                          View verification details
                        </summary>
                        <div className="mt-2 space-y-1.5 text-xs text-muted-foreground">
                          <p>Reviewed independently by {verifier.agent.name}.</p>
                          {verifier.summary ? <p>{verifier.summary}</p> : null}
                          {verifier.failure_message ? (
                            <p className="text-destructive">
                              {verifier.failure_message}
                            </p>
                          ) : null}
                        </div>
                      </details>
                    ) : null}
                  </>
                ) : (
                  <span className="text-muted-foreground">Pending</span>
                )}
              </Item>

              <Item label="Payment">
                {settled
                  ? "Released to agent"
                  : settlementPending
                    ? "Settlement pending on Arc"
                    : "Held in escrow"}
              </Item>
            </div>
          ) : (
            <p className="mt-3 text-sm text-muted-foreground">
              {job.execution.message}
            </p>
          )}
        </section>
      </div>

      {/* Closed by default: for support, not for reading a job. Omitted
          entirely when there is nothing but the ID to show. */}
      {hasTechnical ? (
      <details className="rounded-lg border border-border bg-card">
        <summary className="cursor-pointer px-4 py-2.5 text-xs font-medium text-muted-foreground hover:text-foreground">
          Technical details
        </summary>
        <dl className="space-y-2 border-t border-border px-4 py-3 text-xs">
          <Tech label="Onchain job ID" value={String(job.onchain_job_id)} />
          <Tech label="Contract status" value={job.status} />
          {assignment?.agent.wallet_address ? (
            <Tech label="Agent wallet" value={assignment.agent.wallet_address} />
          ) : null}
          {job.commit_hash ? <Tech label="Commit" value={job.commit_hash} /> : null}
          {job.report_hash ? (
            <Tech label="Verification report" value={job.report_hash} />
          ) : null}
          {job.evidence_hash ? (
            <Tech label="Evidence" value={job.evidence_hash} />
          ) : null}
          {assignment?.settlement_transaction_hash ? (
            <Tech
              label="Settlement transaction"
              value={assignment.settlement_transaction_hash}
            />
          ) : null}
          <Tech
            label="Execution layer"
            value={job.execution.controller.online ? "Online" : "Offline"}
          />
          {job.execution.matching_next_retry_at ? (
            <Tech
              label="Next retry"
              value={new Date(job.execution.matching_next_retry_at).toLocaleString()}
            />
          ) : null}
        </dl>
      </details>
      ) : null}
    </div>
  );
}

/**
 * Rewards are stored with full USDC precision, but "1.000000 USDC" reads
 * like a machine field. Trailing zeros go; real decimals stay.
 */
function formatUsdc(amount: string | number) {
  const value = Number(amount);
  if (!Number.isFinite(value)) return String(amount);
  return String(Number(value.toFixed(6)));
}

function isApproved(verdict: string) {
  const normalized = verdict.toUpperCase();
  return normalized.includes("APPROV") || normalized.includes("PASS");
}

function isRejected(verdict: string) {
  const normalized = verdict.toUpperCase();
  return normalized.includes("REJECT") || normalized.includes("FAIL");
}

/** One inline fact in the summary strip. */
function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-2">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium text-foreground">{value}</dd>
    </div>
  );
}

/** Stacked label/value pair inside the Work summary. */
function Item({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <div className="mt-0.5 text-sm text-foreground">{children}</div>
    </div>
  );
}

/** Monospace key/value line inside Technical details. */
function Tech({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5 sm:flex-row sm:justify-between sm:gap-6">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="break-all font-mono text-foreground sm:text-right">{value}</dd>
    </div>
  );
}

/**
 * One readable sentence instead of a verdict code or the verifier's whole
 * report. The report itself stays available under "View verification
 * details" — nothing is discarded, only demoted.
 */
function verificationLine(verdict: string, summary?: string) {
  if (isApproved(verdict)) return "Approved. All acceptance criteria passed.";
  if (isRejected(verdict)) {
    return "Rejected. The work did not meet the acceptance criteria.";
  }
  if (summary) return summary;
  return titleCase(verdict || "Pending");
}

function VerdictBadge({ verdict }: { verdict: string }) {
  const approved = isApproved(verdict);
  const rejected = isRejected(verdict);
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${
        approved
          ? "border-primary/40 bg-primary/10 text-primary"
          : rejected
            ? "border-destructive/40 bg-destructive/10 text-destructive"
            : "border-border text-muted-foreground"
      }`}
    >
      {approved ? "Verified" : rejected ? "Rejected" : titleCase(verdict)}
    </span>
  );
}

/** "UNDER_REVIEW" reads as "Under review" for a non-engineer. */
function titleCase(value: string) {
  if (!value) return "—";
  const text = value.replaceAll("_", " ").toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
}
