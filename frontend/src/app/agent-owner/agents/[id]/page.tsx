"use client";

import { AgentStatusBadge } from "@/components/agents/agent-status-badge";
import { HostedRuntimeCard } from "@/components/agents/hosted-runtime-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import type { AgentSummary } from "@/types/veyra";
import {
  ArrowLeft,
  Bot,
  Check,
  Copy,
  GitPullRequest,
  Wallet,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

export default function AgentDetailPage() {
  const params = useParams<{ id: string }>();
  const [agent, setAgent] = useState<AgentSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [walletCopied, setWalletCopied] = useState(false);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      setAgent(await apiFetch<AgentSummary>(`/api/v1/agents/${params.id}/`));
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Agent could not be loaded.");
    } finally {
      if (!silent) setLoading(false);
    }
  }, [params.id]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load(true);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [load]);

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-9 w-36" />
        <Skeleton className="h-24 rounded-xl" />
        <div className="grid gap-4 md:grid-cols-2">
          <Skeleton className="h-48 rounded-xl" />
          <Skeleton className="h-48 rounded-xl" />
        </div>
      </div>
    );
  }

  if (error || !agent) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" asChild className="px-0">
          <Link href="/agent-owner/agents">
            <ArrowLeft className="h-4 w-4" /> Back to Agents
          </Link>
        </Button>
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {error ?? "Agent not found."}
        </div>
      </div>
    );
  }

  const assignment = agent.execution.current_assignment;
  const needsAttention =
    !agent.runtime.connected ||
    !agent.runtime.provider_ready ||
    Boolean(agent.provisioning_error);

  async function copyWallet() {
    if (!agent?.worker_wallet_address) return;
    try {
      await navigator.clipboard.writeText(agent.worker_wallet_address);
      setWalletCopied(true);
      window.setTimeout(() => setWalletCopied(false), 1500);
    } catch {
      toast.error("Could not copy the agent wallet address.");
    }
  }

  return (
    <div className="space-y-5">
      <Button variant="ghost" asChild className="px-0">
        <Link href="/agent-owner/agents">
          <ArrowLeft className="h-4 w-4" /> Back to Agents
        </Link>
      </Button>

      <section className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <Bot className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <div className="mb-1.5 flex flex-wrap items-center gap-2">
              <h1 className="truncate text-2xl font-bold tracking-tight">{agent.name}</h1>
              <AgentStatusBadge status={agent.status} />
            </div>
            {agent.description ? (
              <p className="max-w-2xl text-sm text-muted-foreground">{agent.description}</p>
            ) : null}
          </div>
        </div>
      </section>

      {needsAttention ? (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm">
          <p className="font-medium">Agent needs attention</p>
          <p className="mt-1 text-muted-foreground">
            {!agent.runtime.connected
              ? "The runtime is offline."
              : !agent.runtime.provider_ready
                ? "The AI provider is not ready."
                : agent.provisioning_error || "Automatic provisioning needs attention."}
            {" "}Open Advanced settings below to reconnect or retry setup.
          </p>
        </div>
      ) : null}

      <section aria-label="Agent overview" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric label="Connection" value={agent.runtime.connected ? "Connected" : "Offline"} />
        <Metric label="Qualification" value={agent.test_assignment_passed ? "Qualified" : "In progress"} />
        <Metric label="Workload" value={`${agent.execution.active_jobs}/${agent.execution.capacity}`} />
        <Metric label="Earned" value={`${agent.execution.reputation.total_earned_usdc} USDC`} />
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Current work</CardTitle>
          </CardHeader>
          <CardContent>
            {assignment ? (
              <div className="space-y-3">
                <div>
                  <p className="font-semibold">{assignment.job_title}</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {assignment.runtime.progress?.message || assignment.stage_label}
                  </p>
                </div>
                {assignment.failure_message ? (
                  <p className="text-sm text-amber-600">Needs attention: {assignment.failure_message}</p>
                ) : null}
                <Button variant="outline" size="sm" asChild>
                  <Link href={`/agent-owner/assignments?job=${assignment.job_id}`}>
                    <GitPullRequest className="h-4 w-4" /> View assignment
                  </Link>
                </Button>
              </div>
            ) : (
              <div>
                <p className="font-medium">Available for work</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Veyra will match this agent automatically when eligible funded work appears.
                </p>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Wallet className="h-4 w-4" /> Agent wallet
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {agent.worker_wallet_address ? (
              <>
                <div>
                  <p className="text-xs text-muted-foreground">Operational and payout wallet</p>
                  <div className="mt-1.5 flex items-center gap-2">
                    <span
                      className="min-w-0 truncate font-mono text-sm font-medium"
                      title={agent.worker_wallet_address}
                    >
                      {shortenAddress(agent.worker_wallet_address)}
                    </span>
                    <button
                      type="button"
                      onClick={() => void copyWallet()}
                      className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:text-foreground"
                      aria-label={walletCopied ? "Wallet address copied" : "Copy agent wallet address"}
                    >
                      {walletCopied ? <Check className="h-4 w-4 text-primary" /> : <Copy className="h-4 w-4" />}
                    </button>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Badge variant="outline">{agent.wallet_blockchain || "Arc Testnet"}</Badge>
                  <Badge variant="outline">Developer-controlled</Badge>
                </div>
                <Button variant="outline" size="sm" asChild>
                  <Link href="/agent-owner/earnings">View earnings</Link>
                </Button>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">Agent wallet has not been provisioned yet.</p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Capabilities</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <CapabilityRow label="Languages" values={agent.languages} />
          <CapabilityRow label="Frameworks" values={agent.frameworks} />
          <CapabilityRow label="Testing" values={agent.testing_tools} />
          <CapabilityRow label="Task types" values={agent.task_types} />
        </CardContent>
      </Card>

      <details className="rounded-xl border bg-card">
        <summary className="cursor-pointer px-5 py-4 text-sm font-semibold">
          Advanced settings
        </summary>
        <div className="space-y-4 border-t px-4 py-4 sm:px-5">
          <HostedRuntimeCard agent={agent} onRefresh={() => load(true)} />
          <div className="rounded-xl border p-4">
            <p className="text-sm font-semibold">Work policy</p>
            <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
              <Policy label="Budget" value={`${agent.minimum_budget_usdc}–${agent.maximum_budget_usdc} USDC`} />
              <Policy label="Concurrency" value={String(agent.maximum_active_jobs)} />
              <Policy label="Execution limit" value={`${agent.maximum_execution_minutes} min`} />
              <Policy label="Auto assignment" value={agent.auto_claim_enabled ? "On" : "Off"} />
            </dl>
          </div>
        </div>
      </details>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="mt-1.5 text-base font-semibold sm:text-lg">{value}</p>
      </CardContent>
    </Card>
  );
}

function CapabilityRow({ label, values }: { label: string; values: string[] }) {
  if (!values.length) return null;
  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
      <p className="w-24 shrink-0 text-sm text-muted-foreground">{label}</p>
      <div className="flex flex-wrap gap-1.5">
        {values.map((value) => (
          <Badge key={`${label}-${value}`} variant="secondary">{value}</Badge>
        ))}
      </div>
    </div>
  );
}

function Policy({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="mt-1 font-medium">{value}</dd>
    </div>
  );
}

function shortenAddress(address: string) {
  return `${address.slice(0, 8)}…${address.slice(-6)}`;
}
