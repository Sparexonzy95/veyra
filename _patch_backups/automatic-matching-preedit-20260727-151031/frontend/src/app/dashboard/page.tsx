"use client";

import { AgentCard } from "@/components/agents/agent-card";
import { CreateJobDialog } from "@/components/jobs/create-job-dialog";
import { OnchainJobCard } from "@/components/jobs/job-card";
import { useVeyra } from "@/components/providers/veyra-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import type { DashboardResponse, PaginatedAgents } from "@/types/veyra";
import {
  Bot,
  BriefcaseBusiness,
  CheckCircle,
  CircleDollarSign,
  Clock,
  Plus,
  Radio,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

function AgentOwnerDashboard() {
  const { me } = useVeyra();
  const [data, setData] = useState<PaginatedAgents | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await apiFetch<PaginatedAgents>("/api/v1/agents/"));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Agent dashboard could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const agents = data?.results ?? [];
  const active = agents.filter((agent) => agent.status === "ACTIVE").length;
  const online = agents.filter((agent) => agent.engine_connected).length;
  const qualified = agents.filter((agent) => agent.test_assignment_passed).length;

  return (
    <div className="space-y-8">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-center">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            Welcome{me?.user?.display_name ? `, ${me.user.display_name}` : ""}
          </h1>
          <p className="text-muted-foreground">
            Connect, qualify, and operate externally hosted coding agents.
          </p>
        </div>
        <Button asChild><Link href="/dashboard/agents/new"><Plus className="h-4 w-4" /> Create Agent</Link></Button>
      </div>

      {error ? <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">{error}</div> : null}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {loading ? Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-32 rounded-xl" />) : (
          <>
            <Card><CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2"><CardTitle className="text-sm font-medium">Total Agents</CardTitle><Bot className="h-4 w-4 text-muted-foreground" /></CardHeader><CardContent><div className="text-2xl font-bold">{data?.count ?? 0}</div><p className="text-xs text-muted-foreground">In your workspace</p></CardContent></Card>
            <Card><CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2"><CardTitle className="text-sm font-medium">Runtime Online</CardTitle><Radio className="h-4 w-4 text-muted-foreground" /></CardHeader><CardContent><div className="text-2xl font-bold">{online}</div><p className="text-xs text-muted-foreground">Receiving heartbeats</p></CardContent></Card>
            <Card><CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2"><CardTitle className="text-sm font-medium">Qualified</CardTitle><CheckCircle className="h-4 w-4 text-muted-foreground" /></CardHeader><CardContent><div className="text-2xl font-bold">{qualified}</div><p className="text-xs text-muted-foreground">Sandbox test passed</p></CardContent></Card>
            <Card><CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2"><CardTitle className="text-sm font-medium">Active</CardTitle><CircleDollarSign className="h-4 w-4 text-muted-foreground" /></CardHeader><CardContent><div className="text-2xl font-bold">{active}</div><p className="text-xs text-muted-foreground">Eligible for work</p></CardContent></Card>
          </>
        )}
      </div>

      <section>
        <div className="mb-5 flex items-center justify-between">
          <div><h2 className="text-xl font-semibold">Your Agents</h2><p className="text-sm text-muted-foreground">Continue onboarding or inspect active agents.</p></div>
          <Button variant="outline" asChild><Link href="/dashboard/agents">View all</Link></Button>
        </div>
        {loading ? (
          <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 3 }).map((_, index) => <Skeleton key={index} className="h-96 rounded-xl" />)}</div>
        ) : agents.length ? (
          <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">{agents.slice(0, 3).map((agent) => <AgentCard key={agent.id} agent={agent} />)}</div>
        ) : (
          <Card><CardContent className="flex flex-col items-center justify-center py-14 text-center"><Bot className="mb-3 h-8 w-8 text-muted-foreground" /><h3 className="font-semibold">No agents yet</h3><p className="mt-1 text-sm text-muted-foreground">Create a focused agent profile to begin onboarding.</p><Button className="mt-5" asChild><Link href="/dashboard/agents/new"><Plus className="h-4 w-4" /> Create Agent</Link></Button></CardContent></Card>
        )}
      </section>
    </div>
  );
}

function ClientDashboard() {
  const { me } = useVeyra();
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await apiFetch<DashboardResponse>("/api/v1/client/dashboard/"));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Dashboard could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const openJobs = (data?.job_counts.OPEN ?? 0) + (data?.job_counts.FUNDED ?? 0);
  const workingJobs = data?.job_counts.AGENT_WORKING ?? 0;
  const completedJobs = data?.job_counts.COMPLETED ?? 0;

  return (
    <div className="space-y-8">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-center">
        <div><h1 className="text-2xl font-bold tracking-tight">Welcome{me?.user?.display_name ? `, ${me.user.display_name}` : ""}</h1><p className="text-muted-foreground">Create funded GitHub jobs and track verified outcomes.</p></div>
        <Button onClick={() => setCreateOpen(true)}><Plus className="h-4 w-4" /> Create Job</Button>
      </div>

      {error ? <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">{error}</div> : null}

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {loading ? Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-32 rounded-xl" />) : (
          <>
            <Card><CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2"><CardTitle className="text-sm font-medium">USDC Balance</CardTitle><CircleDollarSign className="h-4 w-4 text-muted-foreground" /></CardHeader><CardContent><div className="text-2xl font-bold">{data?.wallet?.usdc_balance ?? "0"} USDC</div><p className="text-xs text-muted-foreground">Arc Testnet</p></CardContent></Card>
            <Card><CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2"><CardTitle className="text-sm font-medium">Open Jobs</CardTitle><BriefcaseBusiness className="h-4 w-4 text-muted-foreground" /></CardHeader><CardContent><div className="text-2xl font-bold">{openJobs}</div><p className="text-xs text-muted-foreground">Waiting for an agent</p></CardContent></Card>
            <Card><CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2"><CardTitle className="text-sm font-medium">In Progress</CardTitle><Clock className="h-4 w-4 text-muted-foreground" /></CardHeader><CardContent><div className="text-2xl font-bold">{workingJobs}</div><p className="text-xs text-muted-foreground">Agent working</p></CardContent></Card>
            <Card><CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2"><CardTitle className="text-sm font-medium">Completed</CardTitle><CheckCircle className="h-4 w-4 text-muted-foreground" /></CardHeader><CardContent><div className="text-2xl font-bold">{completedJobs}</div><p className="text-xs text-muted-foreground">Verified and settled</p></CardContent></Card>
          </>
        )}
      </div>

      <section>
        <div className="mb-5 flex items-center justify-between"><div><h2 className="text-xl font-semibold">Recent Jobs</h2><p className="text-sm text-muted-foreground">Your latest funded work.</p></div><Button variant="outline" asChild><Link href="/dashboard/jobs">View all</Link></Button></div>
        {loading ? (
          <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 3 }).map((_, index) => <Skeleton key={index} className="h-56 rounded-xl" />)}</div>
        ) : data?.jobs.length ? (
          <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">{data.jobs.slice(0, 6).map((job) => <OnchainJobCard key={job.onchain_job_id} job={job} />)}</div>
        ) : (
          <Card><CardContent className="flex flex-col items-center justify-center py-14 text-center"><BriefcaseBusiness className="mb-3 h-8 w-8 text-muted-foreground" /><h3 className="font-semibold">No funded jobs yet</h3><p className="mt-1 text-sm text-muted-foreground">Create your first GitHub job to begin.</p><Button className="mt-5" onClick={() => setCreateOpen(true)}><Plus className="h-4 w-4" /> Create Job</Button></CardContent></Card>
        )}
      </section>

      <CreateJobDialog open={createOpen} onOpenChange={setCreateOpen} onComplete={load} />
    </div>
  );
}

export default function DashboardPage() {
  const { me } = useVeyra();
  const isAgentOwnerOnly = Boolean(
    me?.capabilities?.includes("AGENT_OWNER") && !me.capabilities.includes("CLIENT"),
  );
  return isAgentOwnerOnly ? <AgentOwnerDashboard /> : <ClientDashboard />;
}
