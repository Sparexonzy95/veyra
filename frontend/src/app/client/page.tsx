"use client";

import { PageHeader } from "@/components/dashboard/page-header";
import { Panel } from "@/components/dashboard/panel";
import {
  DashboardPagination,
  PAGE_SIZE,
  pageCount,
  usePageParam,
} from "@/components/dashboard/pagination";
import { StatCard } from "@/components/dashboard/stat-card";
import { EmptyState, ErrorState, LoadingCards } from "@/components/dashboard/states";
import { OnchainJobCard } from "@/components/jobs/job-card";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";
import type { DashboardResponse, JobSummary } from "@/types/veyra";
import {
  BriefcaseBusiness,
  CheckCircle2,
  Clock,
  Loader2,
  Plus,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

function jobState(job: JobSummary) {
  return (job.client_status || job.status || "OPEN").toUpperCase();
}

/**
 * Client Overview: four counts and the most recent jobs. Nothing else.
 *
 * What used to be here and is now gone:
 *
 *   - a Recent activity panel, duplicating the Activity page it linked to;
 *   - a bespoke six-column job table, which was a second design for the
 *     same object the Jobs page already renders as a card. Two designs for
 *     one thing means every future change has to be made twice, and the
 *     table carried columns (repository, deadline) that vanished on mobile.
 *
 * The job grid, the card, the page size and the pagination control are now
 * literally the same components the Jobs page uses.
 */
export default function ClientOverviewPage() {
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await apiFetch<DashboardResponse>("/api/v1/client/dashboard/"));
      setError(null);
    } catch (loadError) {
      setError(
        loadError instanceof Error
          ? loadError.message
          : "Dashboard could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const jobs = useMemo(() => data?.jobs ?? [], [data]);
  const count = (...states: string[]) =>
    jobs.filter((job) => states.includes(jobState(job))).length;

  const metrics = [
    { label: "Open", value: count("OPEN", "FUNDED"), icon: BriefcaseBusiness },
    {
      label: "In Progress",
      value: count("CLAIMED", "AGENT_WORKING", "IN_PROGRESS"),
      icon: Loader2,
    },
    {
      label: "Awaiting Verification",
      value: count("SUBMITTED", "VERIFYING", "AWAITING_VERIFICATION"),
      icon: Clock,
    },
    {
      label: "Completed",
      value: count("COMPLETED", "SETTLED"),
      icon: CheckCircle2,
    },
  ];

  // Same page size as the Jobs grid, from the same constant, so the two
  // pages cannot drift to different sizes.
  const { page, setPage } = usePageParam();
  const totalPages = pageCount(jobs.length, PAGE_SIZE.cards);
  const visible = jobs.slice((page - 1) * PAGE_SIZE.cards, page * PAGE_SIZE.cards);
  const gridRef = useRef<HTMLDivElement | null>(null);

  return (
    <>
      <PageHeader
        title="Overview"
        description="Track published work and settlement at a glance."
        actions={
          <Button asChild size="sm">
            <Link href="/client/jobs/new">
              <Plus className="mr-1.5 h-4 w-4" />
              Create Job
            </Link>
          </Button>
        }
      />

      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}

      <section
        aria-label="Job summary"
        className="grid grid-cols-2 gap-3 lg:grid-cols-4"
      >
        {loading ? (
          <LoadingCards count={4} />
        ) : (
          metrics.map((metric) => (
            <StatCard
              key={metric.label}
              label={metric.label}
              value={metric.value}
              icon={metric.icon}
            />
          ))
        )}
      </section>

      <section aria-labelledby="recent-jobs" className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h2 id="recent-jobs" className="text-sm font-semibold">
            Recent Jobs
          </h2>
          {/* "View all" is kept only because pagination here walks the
              dashboard's own recent set, which is not the whole job list:
              the Jobs page adds drafts, search and status filters. It is a
              different destination, not a second route to the same place. */}
          <Link
            href="/client/jobs"
            className="text-sm font-medium text-primary hover:underline"
          >
            View all
          </Link>
        </div>

        {loading ? (
          <div className="grid items-stretch gap-4 md:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: PAGE_SIZE.cards }).map((_, index) => (
              <div
                key={index}
                className="h-48 animate-pulse rounded-lg border border-border bg-muted/40"
              />
            ))}
          </div>
        ) : jobs.length ? (
          <div ref={gridRef} className="space-y-4">
            <div className="grid items-stretch gap-4 md:grid-cols-2 xl:grid-cols-3">
              {visible.map((job) => (
                <OnchainJobCard key={job.onchain_job_id} job={job} />
              ))}
            </div>
            <DashboardPagination
              page={page}
              totalPages={totalPages}
              totalItems={jobs.length}
              onPageChange={setPage}
              scrollTargetRef={gridRef}
              className="rounded-lg border border-border bg-card"
            />
          </div>
        ) : (
          <Panel>
            <EmptyState
              icon={BriefcaseBusiness}
              title="No jobs yet"
              description="Publish your first job to put an agent to work."
              action={
                <Button asChild size="sm" variant="outline">
                  <Link href="/client/jobs/new">Create Job</Link>
                </Button>
              }
            />
          </Panel>
        )}
      </section>
    </>
  );
}
