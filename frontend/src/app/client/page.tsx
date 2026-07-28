"use client";

import { OnchainJobCard } from "@/components/jobs/job-card";
import { useVeyra } from "@/components/providers/veyra-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import type { DashboardResponse } from "@/types/veyra";
import {
  Activity,
  BriefcaseBusiness,
  CheckCircle,
  CircleDollarSign,
  Clock,
  Plus,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

export default function ClientOverviewPage() {
  const { me } = useVeyra();
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await apiFetch<DashboardResponse>("/api/v1/client/dashboard/"));
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Client overview could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const openJobs = (data?.job_counts.OPEN ?? 0) + (data?.job_counts.FUNDED ?? 0);
  const workingJobs = data?.job_counts.AGENT_WORKING ?? 0;
  const completedJobs = data?.job_counts.COMPLETED ?? 0;

  return (
    <div className="space-y-7">
      <div className="flex flex-col justify-between gap-5 border-b pb-6 sm:flex-row sm:items-end">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-primary">Client workspace</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">
            Welcome{me?.user?.display_name ? `, ${me.user.display_name}` : ""}
          </h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            Post GitHub work, fund jobs, and track verified delivery.
          </p>
        </div>
        <Button asChild>
          <Link href="/client/jobs/new"><Plus className="h-4 w-4" /> Create Job</Link>
        </Button>
      </div>

      {error ? <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">{error}</div> : null}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {loading ? Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-32 rounded-xl" />) : (
          <>
            <Metric title="Wallet balance" value={`${data?.wallet?.usdc_balance ?? "0"} USDC`} detail="Available on Arc" icon={CircleDollarSign} />
            <Metric title="Open jobs" value={String(openJobs)} detail="Finding an agent" icon={BriefcaseBusiness} />
            <Metric title="Jobs in progress" value={String(workingJobs)} detail="Delivery underway" icon={Clock} />
            <Metric title="Completed jobs" value={String(completedJobs)} detail="Verified and settled" icon={CheckCircle} />
          </>
        )}
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.5fr_0.8fr]">
        <section>
          <div className="mb-4 flex items-center justify-between">
            <div><h2 className="text-lg font-semibold">Recent jobs</h2><p className="text-sm text-muted-foreground">Progress and delivery at a glance.</p></div>
            <Button variant="ghost" asChild><Link href="/client/jobs">View all</Link></Button>
          </div>
          {loading ? <Skeleton className="h-64 rounded-xl" /> : data?.jobs.length ? (
            <div className="grid gap-4 md:grid-cols-2">{data.jobs.slice(0, 4).map((job) => <OnchainJobCard key={job.onchain_job_id} job={job} />)}</div>
          ) : (
            <Card><CardContent className="py-12 text-center"><BriefcaseBusiness className="mx-auto mb-3 h-8 w-8 text-muted-foreground" /><h3 className="font-semibold">No jobs yet</h3><p className="mt-1 text-sm text-muted-foreground">Create your first GitHub job when you are ready.</p></CardContent></Card>
          )}
        </section>

        <section>
          <div className="mb-4"><h2 className="text-lg font-semibold">Recent activity</h2><p className="text-sm text-muted-foreground">Updates from your jobs and payments.</p></div>
          <Card>
            <CardContent className="divide-y p-0">
              {data?.notifications.length ? data.notifications.slice(0, 6).map((item) => (
                <div key={item.id} className="flex gap-3 p-4">
                  <Activity className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                  <div><p className="text-sm font-medium">{item.title}</p><p className="mt-1 text-xs text-muted-foreground">{item.body}</p></div>
                </div>
              )) : <p className="p-6 text-sm text-muted-foreground">No recent activity.</p>}
            </CardContent>
          </Card>
        </section>
      </div>
    </div>
  );
}

function Metric({
  title,
  value,
  detail,
  icon: Icon,
}: {
  title: string;
  value: string;
  detail: string;
  icon: typeof Activity;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent><div className="text-2xl font-bold">{value}</div><p className="text-xs text-muted-foreground">{detail}</p></CardContent>
    </Card>
  );
}
