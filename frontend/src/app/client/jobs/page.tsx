"use client";

import { PageHeader } from "@/components/dashboard/page-header";
import { Panel } from "@/components/dashboard/panel";
import {
  DashboardPagination,
  PAGE_SIZE,
  pageCount,
  usePageParam,
} from "@/components/dashboard/pagination";
import { EmptyState, ErrorState } from "@/components/dashboard/states";
import { CreateJobDialog } from "@/components/jobs/create-job-dialog";
import { DraftJobCard, OnchainJobCard } from "@/components/jobs/job-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { apiFetch, deleteRequest } from "@/lib/api";
import type { JobDraft, JobSummary } from "@/types/veyra";
import { BriefcaseBusiness, Plus, Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

type Paginated<T> = { count: number; next: string | null; previous: string | null; results: T[] };

export default function JobsPage() {
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [drafts, setDrafts] = useState<JobDraft[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("ALL");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [selectedDraft, setSelectedDraft] = useState<JobDraft | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [jobPage, draftPage] = await Promise.all([
        apiFetch<Paginated<JobSummary>>("/api/v1/client/jobs/?page_size=100"),
        apiFetch<Paginated<JobDraft>>("/api/v1/client/job-drafts/?page_size=100"),
      ]);
      setJobs(jobPage.results);
      setDrafts(draftPage.results.filter((draft) => draft.status !== "FUNDED"));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Jobs could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("github") === "connected") {
      setSelectedDraft(null);
      setDialogOpen(true);
      window.history.replaceState({}, "", "/client/jobs");
    }
  }, []);

  const filteredJobs = useMemo(() => jobs.filter((job) => {
    const matchesQuery = `${job.title} ${job.github_issue_url}`.toLowerCase().includes(query.toLowerCase());
    const matchesStatus = filter === "ALL" || job.client_status === filter;
    return matchesQuery && matchesStatus;
  }), [filter, jobs, query]);

  const filteredDrafts = useMemo(() => drafts.filter((draft) => {
    const matchesQuery = `${draft.issue_title} ${draft.github_issue_url}`.toLowerCase().includes(query.toLowerCase());
    return matchesQuery && (filter === "ALL" || filter === "DRAFTS");
  }), [drafts, filter, query]);

  /**
   * Drafts and on-chain jobs share one grid, so they are paginated as one
   * sequence with drafts first. Search and status filtering run before the
   * slice, so page 2 is page 2 of the *filtered* set, not of everything.
   *
   * The slice is local because the search box filters across every job the
   * client owns; paging the API instead would silently reduce search to
   * "matches on the current page". The fetch stays bounded at 100.
   */
  const { page, setPage, resetToFirstPage } = usePageParam();
  const combined = useMemo(
    () => [
      ...filteredDrafts.map((draft) => ({ kind: "draft" as const, draft })),
      ...filteredJobs.map((job) => ({ kind: "job" as const, job })),
    ],
    [filteredDrafts, filteredJobs],
  );
  const totalPages = pageCount(combined.length, PAGE_SIZE.cards);
  const visible = combined.slice(
    (page - 1) * PAGE_SIZE.cards,
    page * PAGE_SIZE.cards,
  );
  const gridRef = useRef<HTMLDivElement | null>(null);

  function openNew() {
    setSelectedDraft(null);
    setDialogOpen(true);
  }

  function openDraft(draft: JobDraft) {
    setSelectedDraft(draft);
    setDialogOpen(true);
  }

  async function removeDraft(draft: JobDraft) {
    try {
      await deleteRequest(`/api/v1/client/job-drafts/${draft.id}/`);
      toast.success("Draft deleted.");
      await load();
    } catch (deleteError) {
      toast.error(deleteError instanceof Error ? deleteError.message : "Draft could not be deleted.");
    }
  }

  return (
    <>
      <PageHeader
        title="Jobs"
        description="Manage published work and track progress."
        actions={
          <Button size="sm" onClick={openNew}>
            <Plus className="mr-1.5 h-4 w-4" /> Create Job
          </Button>
        }
      />

      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="relative w-full md:max-w-xs">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              // Without this, narrowing the search while on page 3 lands on
              // an empty page instead of the first matches.
              resetToFirstPage();
            }}
            placeholder="Search jobs..."
            className="pl-9"
          />
        </div>
        {/* Filters scroll horizontally on small screens instead of wrapping
            into a tall block that pushes the list below the fold. */}
        <Tabs
          value={filter}
          onValueChange={(next) => {
            setFilter(next);
            resetToFirstPage();
          }}
          className="w-full md:w-auto"
        >
          <TabsList className="w-full justify-start overflow-x-auto md:w-auto">
            <TabsTrigger value="ALL">All</TabsTrigger>
            <TabsTrigger value="DRAFTS">Drafts</TabsTrigger>
            <TabsTrigger value="OPEN">Open</TabsTrigger>
            <TabsTrigger value="AGENT_WORKING">In progress</TabsTrigger>
            <TabsTrigger value="UNDER_REVIEW">Review</TabsTrigger>
            <TabsTrigger value="COMPLETED">Completed</TabsTrigger>
            <TabsTrigger value="REFUNDED">Refunded</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}

      {loading ? (
        <div className="grid items-stretch gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: PAGE_SIZE.cards }).map((_, index) => (
            <div
              key={index}
              className="h-48 animate-pulse rounded-lg border border-border bg-muted/40"
            />
          ))}
        </div>
      ) : combined.length ? (
        <div ref={gridRef} className="space-y-4">
          <div className="grid items-stretch gap-4 md:grid-cols-2 xl:grid-cols-3">
            {visible.map((entry) =>
              entry.kind === "draft" ? (
                <DraftJobCard
                  key={`draft-${entry.draft.id}`}
                  draft={entry.draft}
                  onOpen={openDraft}
                  onDelete={removeDraft}
                />
              ) : (
                <OnchainJobCard
                  key={`job-${entry.job.onchain_job_id}`}
                  job={entry.job}
                />
              ),
            )}
          </div>
          <DashboardPagination
            page={page}
            totalPages={totalPages}
            totalItems={combined.length}
            onPageChange={setPage}
            scrollTargetRef={gridRef}
            className="rounded-lg border border-border bg-card"
          />
        </div>
      ) : (
        <Panel>
          {/* No Create Job button here: it is already the PageHeader action
              a few hundred pixels above, and repeating it was one of the
              duplicated actions on this page. */}
          <EmptyState
            icon={BriefcaseBusiness}
            title="No jobs found"
            description="Create a job or change your filters."
          />
        </Panel>
      )}

      <CreateJobDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        initialDraft={selectedDraft}
        onComplete={load}
      />
    </>
  );
}
