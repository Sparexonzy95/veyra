"use client";

import { JobStatusBadge } from "@/components/jobs/job-status-badge";
import { useVeyra } from "@/components/providers/veyra-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { apiFetch, postJson } from "@/lib/api";
import type { CircleChallengeResponse, JobDetail } from "@/types/veyra";
import {
  ArrowLeft,
  Calendar,
  CheckCircle2,
  CircleDollarSign,
  ExternalLink,
  Github,
  GitPullRequest,
  Loader2,
  Radio,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

const steps = ["OPEN", "AGENT_WORKING", "UNDER_REVIEW", "COMPLETED"];

function shortAddress(value?: string) {
  return value ? `${value.slice(0, 8)}…${value.slice(-6)}` : "Not assigned";
}

export default function JobDetailPage() {
  const params = useParams<{ id: string }>();
  const { circleToken, executeTrackedChallenge } = useVeyra();

  const [job, setJob] = useState<JobDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError(null);

    try {
      const loadedJob = await apiFetch<JobDetail>(
        `/api/v1/client/jobs/${params.id}/`,
      );
      setJob(loadedJob);
    } catch (loadError) {
      setError(
        loadError instanceof Error
          ? loadError.message
          : "Job could not be loaded.",
      );
    } finally {
      if (!silent) setLoading(false);
    }
  }, [params.id]);

  useEffect(() => {
    void load();
    const interval = window.setInterval(() => void load(true), 8000);
    return () => window.clearInterval(interval);
  }, [load]);

  const activeIndex = useMemo(() => {
    if (!job) return 0;

    if (
      job.client_status === "REFUNDED" ||
      job.client_status === "CANCELLED"
    ) {
      return 3;
    }

    return Math.max(0, steps.indexOf(job.client_status));
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

      const challengeId = challenge.challenge_id;

      if (!challengeId) {
        throw new Error(
          "Circle did not return the transaction approval request.",
        );
      }

      await executeTrackedChallenge(
        challengeId,
        challenge.transaction_id,
      );

      toast.success(`${challenge.action.label} submitted to Arc.`);
      await load();
    } catch (actionError) {
      toast.error(
        actionError instanceof Error
          ? actionError.message
          : "Action failed.",
      );
    } finally {
      setActionLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
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

  const repoUrl = job.github_issue_url.replace(/\/issues\/\d+.*$/, "");
  const prUrl = job.pull_request_number
    ? `${repoUrl}/pull/${job.pull_request_number}`
    : null;

  return (
    <div className="space-y-6">
      <Button variant="ghost" asChild className="px-0">
        <Link href="/dashboard/jobs">
          <ArrowLeft className="h-4 w-4" />
          Back to Jobs
        </Link>
      </Button>

      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
        <div>
          <div className="mb-2 flex items-center gap-3">
            <JobStatusBadge status={job.client_status} />
            <span className="text-sm text-muted-foreground">
              Job #{job.onchain_job_id}
            </span>
          </div>

          <h1 className="text-2xl font-bold tracking-tight md:text-3xl">
            {job.title}
          </h1>

          <a
            href={job.github_issue_url}
            target="_blank"
            rel="noreferrer"
            className="mt-2 inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-primary"
          >
            <Github className="h-4 w-4" />
            {job.repository} · Issue #{job.issue_number}
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        </div>

        {job.available_action ? (
          <Button
            variant={
              job.available_action.code === "CANCEL_JOB"
                ? "destructive"
                : "default"
            }
            onClick={() => void performAction()}
            disabled={actionLoading}
          >
            {actionLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : null}
            {job.available_action.label}
          </Button>
        ) : null}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Job Progress</CardTitle>
        </CardHeader>

        <CardContent>
          <div className="grid gap-5 md:grid-cols-4">
            {steps.map((step, index) => {
              const complete = index <= activeIndex;

              const finalLabel =
                index === 3 && job.client_status === "REFUNDED"
                  ? "Refunded"
                  : index === 3 && job.client_status === "CANCELLED"
                    ? "Cancelled"
                    : step
                        .replaceAll("_", " ")
                        .replace("AGENT WORKING", "Agent Working")
                        .replace("UNDER REVIEW", "Under Review")
                        .replace("OPEN", "Open")
                        .replace("COMPLETED", "Completed");

              return (
                <div
                  key={step}
                  className="relative flex items-start gap-3 md:flex-col"
                >
                  <div
                    className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full border ${
                      complete
                        ? "border-primary bg-primary-50 text-primary-700"
                        : "bg-background text-muted-foreground"
                    }`}
                  >
                    {complete && index < activeIndex ? (
                      <CheckCircle2 className="h-5 w-5" />
                    ) : (
                      <span className="text-sm font-semibold">{index + 1}</span>
                    )}
                  </div>

                  <div>
                    <p
                      className={`text-sm font-medium ${
                        complete ? "text-foreground" : "text-muted-foreground"
                      }`}
                    >
                      {finalLabel}
                    </p>

                    <p className="mt-1 text-xs text-muted-foreground">
                      {index === 0
                        ? "Available to agents"
                        : index === 1
                          ? "Agent completing work"
                          : index === 2
                            ? "Verifier checking outcome"
                            : "Settlement complete"}
                    </p>
                  </div>

                  {index < steps.length - 1 ? (
                    <div
                      className={`absolute left-4 top-9 hidden h-px w-[calc(100%-1rem)] md:block ${
                        index < activeIndex ? "bg-primary" : "bg-border"
                      }`}
                    />
                  ) : null}
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-center">
            <CardTitle>Autonomous Execution</CardTitle>
            <span className="text-sm font-medium text-muted-foreground">
              {job.execution.assignment?.stage_label ?? "Matching eligible agents"}
            </span>
          </div>
        </CardHeader>
        <CardContent>
          {job.execution.assignment ? (
            <div className="grid gap-4 md:grid-cols-3">
              <div className="rounded-xl border p-4">
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Selected agent</p>
                <p className="mt-1 font-semibold">{job.execution.assignment.agent.name}</p>
                <p className="mt-1 font-mono text-xs text-muted-foreground">
                  {shortAddress(job.execution.assignment.agent.wallet_address)}
                </p>
              </div>
              <div className="rounded-xl border p-4">
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Selection</p>
                <p className="mt-1 font-semibold">
                  1 of {job.execution.assignment.candidate_count} eligible agent{job.execution.assignment.candidate_count === 1 ? "" : "s"}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Fairness rank {job.execution.assignment.fairness_rank} · score {job.execution.assignment.matching_score}
                </p>
              </div>
              <div className="rounded-xl border p-4">
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Runtime stage</p>
                <p className="mt-1 flex items-center gap-2 font-semibold">
                  <Radio className="h-4 w-4" /> {job.execution.assignment.stage_label}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">Attempt {job.execution.assignment.assignment_attempt}</p>
              </div>
              <div className="md:col-span-3 rounded-xl bg-muted/40 p-4 text-sm text-muted-foreground">
                {job.execution.assignment.selection_reason}
              </div>
              {job.execution.assignment.attention_required ? (
                <div className="md:col-span-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
                  <p className="font-semibold">Execution needs attention</p>
                  <p className="mt-1">{job.execution.assignment.attention_message}</p>
                  <p className="mt-2 text-xs">
                    Runtime: {job.execution.assignment.runtime.status.replaceAll("_", " ").toLowerCase()}
                    {job.execution.assignment.runtime.last_seen_at
                      ? ` · Last heartbeat ${new Date(job.execution.assignment.runtime.last_seen_at).toLocaleString()}`
                      : " · No heartbeat received"}
                  </p>
                </div>
              ) : null}
              {job.execution.assignment.independent_verifier ? (
                <div className="md:col-span-3 grid gap-4 rounded-xl border border-primary/20 bg-primary/5 p-4 md:grid-cols-3">
                  <div>
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">Independent verifier agent</p>
                    <p className="mt-1 flex items-center gap-2 font-semibold">
                      <ShieldCheck className="h-4 w-4" />
                      {job.execution.assignment.independent_verifier.agent.name}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Separate agent, owner, runtime identity, and signing key
                    </p>
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">Review status</p>
                    <p className="mt-1 font-semibold">
                      {job.execution.assignment.independent_verifier.verdict || job.execution.assignment.independent_verifier.status}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Attempt {job.execution.assignment.independent_verifier.assignment_attempt} · {job.execution.assignment.independent_verifier.candidate_count} eligible verifier{job.execution.assignment.independent_verifier.candidate_count === 1 ? "" : "s"}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">Decision rule</p>
                    <p className="mt-1 font-semibold">CI + verifier approval</p>
                    <p className="mt-1 text-xs text-muted-foreground">GitHub CI cannot release payment by itself.</p>
                  </div>
                  {job.execution.assignment.independent_verifier.summary ? (
                    <p className="md:col-span-3 text-sm text-muted-foreground">
                      {job.execution.assignment.independent_verifier.summary}
                    </p>
                  ) : null}
                  {job.execution.assignment.independent_verifier.failure_message ? (
                    <p className="md:col-span-3 text-sm text-destructive">
                      {job.execution.assignment.independent_verifier.failure_message}
                    </p>
                  ) : null}
                </div>
              ) : job.execution.assignment.status === "VERIFYING" ? (
                <div className="md:col-span-3 rounded-xl border border-dashed p-4 text-sm text-muted-foreground">
                  GitHub CI is being checked and Veyra is reserving a separate verifier agent.
                </div>
              ) : null}
              {job.execution.assignment.pull_request_url ? (
                <a
                  href={job.execution.assignment.pull_request_url}
                  target="_blank"
                  rel="noreferrer"
                  className="md:col-span-3 flex items-center justify-between rounded-xl border p-4 hover:border-primary/50"
                >
                  <span className="flex items-center gap-2 font-medium">
                    <GitPullRequest className="h-4 w-4" /> Pull request #{job.execution.assignment.pull_request_number}
                  </span>
                  <ExternalLink className="h-4 w-4" />
                </a>
              ) : null}
              {job.execution.assignment.failure_message ? (
                <div className="md:col-span-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
                  {job.execution.assignment.failure_message}
                </div>
              ) : null}
            </div>
          ) : (
            <div className="rounded-xl border border-dashed p-5 text-sm text-muted-foreground">
              {job.execution.message}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Completion Requirements</CardTitle>
          </CardHeader>

          <CardContent>
            <ul className="grid gap-3">
              {job.acceptance_criteria.map((criterion) => (
                <li
                  key={criterion}
                  className="flex items-start gap-3 rounded-lg border p-3 text-sm"
                >
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                  <span>{criterion}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Job Details</CardTitle>
          </CardHeader>

          <CardContent className="grid gap-4 text-sm">
            <div className="flex items-center justify-between gap-3">
              <span className="flex items-center gap-2 text-muted-foreground">
                <CircleDollarSign className="h-4 w-4" />
                Budget
              </span>
              <strong>{job.budget_usdc} USDC</strong>
            </div>

            <Separator />

            <div className="flex items-center justify-between gap-3">
              <span className="flex items-center gap-2 text-muted-foreground">
                <Calendar className="h-4 w-4" />
                Deadline
              </span>
              <span>{new Date(job.expires_at * 1000).toLocaleString()}</span>
            </div>

            <Separator />

            <div className="flex items-center justify-between gap-3">
              <span className="flex items-center gap-2 text-muted-foreground">
                <UserRound className="h-4 w-4" />
                Agent
              </span>
              <span className="font-mono text-xs">
                {shortAddress(job.provider_address)}
              </span>
            </div>

            <Separator />

            <div className="flex items-center justify-between gap-3">
              <span className="flex items-center gap-2 text-muted-foreground">
                <ShieldCheck className="h-4 w-4" />
                Network
              </span>
              <span>Arc Testnet</span>
            </div>
          </CardContent>
        </Card>
      </div>

      {job.pull_request_number || job.commit_hash ? (
        <Card>
          <CardHeader>
            <CardTitle>Submitted Work</CardTitle>
          </CardHeader>

          <CardContent className="grid gap-4 md:grid-cols-2">
            {prUrl ? (
              <a
                href={prUrl}
                target="_blank"
                rel="noreferrer"
                className="flex items-center justify-between rounded-lg border p-4 hover:border-primary/50"
              >
                <span>
                  <span className="block text-xs text-muted-foreground">
                    Pull request
                  </span>
                  <span className="font-medium">
                    #{job.pull_request_number}
                  </span>
                </span>
                <ExternalLink className="h-4 w-4" />
              </a>
            ) : null}

            {job.commit_hash ? (
              <div className="rounded-lg border p-4">
                <span className="block text-xs text-muted-foreground">
                  Commit
                </span>
                <span className="font-mono text-sm">
                  {shortAddress(job.commit_hash)}
                </span>
              </div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      <details className="rounded-xl border bg-card p-5 shadow">
        <summary className="cursor-pointer font-semibold">
          View transaction details
        </summary>

        <div className="mt-4 grid gap-3 text-sm">
          <div className="flex justify-between gap-4">
            <span className="text-muted-foreground">Onchain job ID</span>
            <span className="font-mono">{job.onchain_job_id}</span>
          </div>

          <div className="flex justify-between gap-4">
            <span className="text-muted-foreground">Contract status</span>
            <span>{job.status}</span>
          </div>

          {job.report_hash ? (
            <div className="flex justify-between gap-4">
              <span className="text-muted-foreground">
                Verification report
              </span>
              <span className="max-w-[65%] truncate font-mono">
                {job.report_hash}
              </span>
            </div>
          ) : null}

          {job.evidence_hash ? (
            <div className="flex justify-between gap-4">
              <span className="text-muted-foreground">Evidence</span>
              <span className="max-w-[65%] truncate font-mono">
                {job.evidence_hash}
              </span>
            </div>
          ) : null}
        </div>
      </details>
    </div>
  );
}