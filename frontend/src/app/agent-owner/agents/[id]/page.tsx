"use client";

import { AgentStatusBadge } from "@/components/agents/agent-status-badge";
import { HostedRuntimeCard } from "@/components/agents/hosted-runtime-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import type { AgentSummary } from "@/types/veyra";
import { ArrowLeft, Bot, GitPullRequest } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

export default function AgentDetailPage() {
  const params = useParams<{ id: string }>();
  const [agent, setAgent] = useState<AgentSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
    }, 10000);
    return () => window.clearInterval(timer);
  }, [load]);

  if (loading) {
    return <div className="space-y-6"><Skeleton className="h-9 w-36" /><Skeleton className="h-28 rounded-xl" /><Skeleton className="h-[32rem] rounded-xl" /></div>;
  }

  if (error || !agent) {
    return <div className="space-y-4"><Button variant="ghost" asChild className="px-0"><Link href="/agent-owner/agents"><ArrowLeft className="h-4 w-4" /> Back to Agents</Link></Button><div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">{error ?? "Agent not found."}</div></div>;
  }

  const assignment = agent.execution.current_assignment;

  return (
    <div className="space-y-6">
      <Button variant="ghost" asChild className="px-0"><Link href="/agent-owner/agents"><ArrowLeft className="h-4 w-4" /> Back to Agents</Link></Button>
      <div className="flex items-start gap-4">
        <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-primary/10 text-primary"><Bot className="h-7 w-7" /></div>
        <div><div className="mb-2"><AgentStatusBadge status={agent.status} /></div><h1 className="text-2xl font-bold tracking-tight md:text-3xl">{agent.name}</h1></div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <MetricCard label="Connection" value={agent.runtime.connected ? "Connected" : "Offline"} />
        <MetricCard label="Provider readiness" value={agent.runtime.provider_ready ? "Ready" : "Needs attention"} />
        <MetricCard label="Qualification status" value={agent.test_assignment_passed ? "Qualified" : "In progress"} />
        <MetricCard label="Current workload" value={`${agent.execution.active_jobs}/${agent.execution.capacity}`} />
        <MetricCard label="Earnings" value={`${agent.execution.reputation.total_earned_usdc} USDC`} />
        <MetricCard label="Assignments" value={String(agent.execution.active_jobs)} />
      </div>

      <HostedRuntimeCard agent={agent} onRefresh={() => load(true)} />

      <Card>
        <CardHeader><CardTitle>Assignments</CardTitle></CardHeader>
        <CardContent>
          {assignment ? (
            <div className="rounded-xl border border-primary/30 bg-primary/5 p-4">
              <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
                <div><p className="font-semibold">{assignment.job_title}</p><p className="mt-1 text-sm text-muted-foreground">{assignment.stage_label}</p></div>
                <Button variant="outline" size="sm" asChild><Link href={`/agent-owner/assignments?job=${assignment.job_id}`}><GitPullRequest className="h-4 w-4" /> View assignment</Link></Button>
              </div>
              {assignment.failure_message ? <p className="mt-3 text-sm text-amber-600">Needs attention: {assignment.failure_message}</p> : null}
            </div>
          ) : (
            <div className="rounded-xl border border-dashed p-5 text-sm text-muted-foreground">Finding an agent match for eligible funded work.</div>
          )}
        </CardContent>
      </Card>

      <details className="rounded-xl border bg-card p-5">
        <summary className="cursor-pointer font-semibold">Work policy</summary>
        <div className="mt-5 grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
          <div><p className="text-muted-foreground">Budget range</p><p className="mt-1 font-medium">{agent.minimum_budget_usdc}–{agent.maximum_budget_usdc} USDC</p></div>
          <div><p className="text-muted-foreground">Concurrent jobs</p><p className="mt-1 font-medium">{agent.maximum_active_jobs}</p></div>
          <div><p className="text-muted-foreground">Execution limit</p><p className="mt-1 font-medium">{agent.maximum_execution_minutes} minutes</p></div>
          <div><p className="text-muted-foreground">Automatic assignment</p><Badge className="mt-1" variant={agent.auto_claim_enabled ? "default" : "outline"}>{agent.auto_claim_enabled ? "On" : "Off"}</Badge></div>
        </div>
      </details>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return <Card><CardContent className="p-5"><p className="text-sm text-muted-foreground">{label}</p><p className="mt-2 text-xl font-semibold">{value}</p></CardContent></Card>;
}
