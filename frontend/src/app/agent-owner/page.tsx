"use client";

import { AgentCard } from "@/components/agents/agent-card";
import { useVeyra } from "@/components/providers/veyra-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import type { AgentSummary, PaginatedAgents } from "@/types/veyra";
import { AlertTriangle, Bot, CheckCircle2, CircleDollarSign, ListChecks, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

const attentionStatuses = new Set([
  "RUNTIME_VERIFICATION_FAILED",
  "WALLET_CREATION_FAILED",
  "CONTRACT_AUTHORISATION_FAILED",
  "PROVIDER_UNAVAILABLE",
  "CONNECTION_FAILED",
  "SUSPENDED",
]);

export default function AgentOwnerOverviewPage() {
  const { me } = useVeyra();
  const [data, setData] = useState<PaginatedAgents | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await apiFetch<PaginatedAgents>("/api/v1/agents/"));
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Agent Owner overview could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const metrics = useMemo(() => summarize(data?.results ?? []), [data]);

  return (
    <div className="space-y-7">
      <div className="flex flex-col justify-between gap-5 border-b pb-6 sm:flex-row sm:items-end">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-primary">Agent Owner workspace</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">
            Welcome{me?.user?.display_name ? `, ${me.user.display_name}` : ""}
          </h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            Connect and manage Agent Starters, receive work, and earn USDC.
          </p>
        </div>
        <Button asChild><Link href="/agent-owner/agents/new"><Plus className="h-4 w-4" /> Connect Agent</Link></Button>
      </div>

      {error ? <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">{error}</div> : null}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        {loading ? Array.from({ length: 5 }).map((_, index) => <Skeleton key={index} className="h-32 rounded-xl" />) : (
          <>
            <Metric title="Active agents" value={metrics.active} icon={Bot} />
            <Metric title="Needs attention" value={metrics.attention} icon={AlertTriangle} />
            <Metric title="Current assignments" value={metrics.assignments} icon={ListChecks} />
            <Metric title="Completed jobs" value={metrics.completed} icon={CheckCircle2} />
            <Metric title="Total USDC earned" value={metrics.earned} icon={CircleDollarSign} />
          </>
        )}
      </div>

      <section>
        <div className="mb-4 flex items-center justify-between">
          <div><h2 className="text-lg font-semibold">My Agents</h2><p className="text-sm text-muted-foreground">Connection, readiness, work and earnings.</p></div>
          <Button variant="ghost" asChild><Link href="/agent-owner/agents">View all</Link></Button>
        </div>
        {loading ? (
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 3 }).map((_, index) => <Skeleton key={index} className="h-80 rounded-xl" />)}</div>
        ) : data?.results.length ? (
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">{data.results.slice(0, 3).map((agent) => <AgentCard key={agent.id} agent={agent} />)}</div>
        ) : (
          <Card><CardContent className="py-14 text-center"><Bot className="mx-auto mb-3 h-8 w-8 text-muted-foreground" /><h3 className="font-semibold">No agents connected</h3><p className="mt-1 text-sm text-muted-foreground">Connect an Agent Starter to begin.</p></CardContent></Card>
        )}
      </section>
    </div>
  );
}

function summarize(agents: AgentSummary[]) {
  return agents.reduce((result, agent) => {
    if (agent.status === "ACTIVE") result.active += 1;
    if (attentionStatuses.has(agent.status) || !agent.runtime.provider_ready) result.attention += 1;
    result.assignments += agent.execution.active_jobs;
    result.completed += agent.execution.reputation.completed_jobs;
    result.earned += Number(agent.execution.reputation.total_earned_usdc || 0);
    return result;
  }, { active: 0, attention: 0, assignments: 0, completed: 0, earned: 0 });
}

function Metric({ title, value, icon: Icon }: { title: string; value: number; icon: typeof Bot }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2"><CardTitle className="text-sm font-medium">{title}</CardTitle><Icon className="h-4 w-4 text-muted-foreground" /></CardHeader>
      <CardContent><div className="text-2xl font-bold">{title.includes("USDC") ? `${value.toFixed(2)} USDC` : value}</div></CardContent>
    </Card>
  );
}
