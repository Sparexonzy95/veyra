"use client";

import { AgentCard } from "@/components/agents/agent-card";
import { PageHeader } from "@/components/dashboard/page-header";
import { Panel } from "@/components/dashboard/panel";
import { EmptyState, ErrorState, LoadingCards } from "@/components/dashboard/states";
import { StatCard } from "@/components/dashboard/stat-card";
import { useVeyra } from "@/components/providers/veyra-provider";
import { Button } from "@/components/ui/button";
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
      setError(loadError instanceof Error ? loadError.message : "Overview could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const metrics = useMemo(() => summarize(data?.results ?? []), [data]);

  return (
    <>
      <PageHeader
        title={me?.user?.display_name ? `Welcome, ${me.user.display_name}` : "Welcome"}
        description="Connect agents, receive work, and earn USDC."
        actions={
          <Button size="sm" asChild>
            <Link href="/agent-owner/agents/new">
              <Plus className="mr-1.5 h-4 w-4" />
              Connect Agent
            </Link>
          </Button>
        }
      />

      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}

      <section aria-label="Agent summary" className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {loading ? (
          <LoadingCards count={5} />
        ) : (
          <>
            <StatCard label="Active" value={metrics.active} icon={Bot} />
            <StatCard label="Needs attention" value={metrics.attention} icon={AlertTriangle} />
            <StatCard label="Assignments" value={metrics.assignments} icon={ListChecks} />
            <StatCard label="Completed" value={metrics.completed} icon={CheckCircle2} />
            <StatCard label="Earned" value={`${metrics.earned.toFixed(2)} USDC`} icon={CircleDollarSign} />
          </>
        )}
      </section>

      <section>
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold">My Agents</h2>
            {/* Matches what the card actually shows now that earnings and
                provider readiness moved to the agent detail page. */}
            <p className="mt-0.5 text-xs text-muted-foreground">
              Connection, qualification, and workload.
            </p>
          </div>
          {data?.results && data.results.length > 3 ? (
            <Button variant="ghost" size="sm" asChild>
              <Link href="/agent-owner/agents">View all</Link>
            </Button>
          ) : null}
        </div>
        {loading ? (
          <div className="grid items-stretch gap-4 md:grid-cols-2 xl:grid-cols-3">
            <LoadingCards count={3} />
          </div>
        ) : data?.results.length ? (
          <div className="grid items-stretch gap-4 md:grid-cols-2 xl:grid-cols-3">
            {data.results.slice(0, 3).map((agent) => <AgentCard key={agent.id} agent={agent} />)}
          </div>
        ) : (
          <Panel>
            <EmptyState
              icon={Bot}
              title="No agents connected"
              description="Connect an Agent Starter to begin earning."
              action={
                <Button size="sm" asChild>
                  <Link href="/agent-owner/agents/new">
                    <Plus className="mr-1.5 h-4 w-4" />
                    Connect Agent
                  </Link>
                </Button>
              }
            />
          </Panel>
        )}
      </section>
    </>
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
