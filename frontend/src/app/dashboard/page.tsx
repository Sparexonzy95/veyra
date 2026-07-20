"use client";

import { CreateJobDialog } from "@/components/jobs/create-job-dialog";
import { OnchainJobCard } from "@/components/jobs/job-card";
import { useVeyra } from "@/components/providers/veyra-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import type { DashboardResponse } from "@/types/veyra";
import { BriefcaseBusiness, CheckCircle, CircleDollarSign, Clock, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

export default function DashboardPage() {
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
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Welcome{me?.user?.display_name ? `, ${me.user.display_name}` : ""}</h1>
          <p className="text-muted-foreground">Create funded GitHub jobs and track verified outcomes.</p>
        </div>
        <Button onClick={() => setCreateOpen(true)}><Plus className="h-4 w-4" /> Create Job</Button>
      </div>

      {error ? <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">{error}</div> : null}

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {loading ? Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-32 rounded-xl" />) : (
          <>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">USDC Balance</CardTitle>
                <CircleDollarSign className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent><div className="text-2xl font-bold">{data?.wallet?.usdc_balance ?? "0"} USDC</div><p className="text-xs text-muted-foreground">Arc Testnet</p></CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Open Jobs</CardTitle>
                <BriefcaseBusiness className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent><div className="text-2xl font-bold">{openJobs}</div><p className="text-xs text-muted-foreground">Waiting for an agent</p></CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">In Progress</CardTitle>
                <Clock className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent><div className="text-2xl font-bold">{workingJobs}</div><p className="text-xs text-muted-foreground">Agent working</p></CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Completed</CardTitle>
                <CheckCircle className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent><div className="text-2xl font-bold">{completedJobs}</div><p className="text-xs text-muted-foreground">Verified and settled</p></CardContent>
            </Card>
          </>
        )}
      </div>

      <section>
        <div className="mb-5 flex items-center justify-between">
          <div><h2 className="text-xl font-semibold">Recent Jobs</h2><p className="text-sm text-muted-foreground">Your latest funded work.</p></div>
          <Button variant="outline" asChild><Link href="/dashboard/jobs">View all</Link></Button>
        </div>
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
