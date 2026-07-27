"use client";

import { CreateJobDialog } from "@/components/jobs/create-job-dialog";
import { DraftJobCard, OnchainJobCard } from "@/components/jobs/job-card";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { apiFetch, deleteRequest } from "@/lib/api";
import type { JobDraft, JobSummary } from "@/types/veyra";
import { BriefcaseBusiness, Plus, Search, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
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
      window.history.replaceState({}, "", "/dashboard/jobs");
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
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-center">
        <div><h1 className="text-2xl font-bold tracking-tight">My Jobs</h1><p className="text-muted-foreground">Create, fund and track GitHub work.</p></div>
        <Button onClick={openNew}><Plus className="h-4 w-4" /> Create Job</Button>
      </div>

      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div className="relative w-full md:max-w-sm"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search jobs..." className="pl-9" /></div>
        <Tabs value={filter} onValueChange={setFilter}>
          <TabsList className="flex-wrap">
            <TabsTrigger value="ALL">All</TabsTrigger>
            <TabsTrigger value="DRAFTS">Drafts</TabsTrigger>
            <TabsTrigger value="OPEN">Open</TabsTrigger>
            <TabsTrigger value="AGENT_WORKING">In Progress</TabsTrigger>
            <TabsTrigger value="UNDER_REVIEW">Reviewing</TabsTrigger>
            <TabsTrigger value="COMPLETED">Completed</TabsTrigger>
            <TabsTrigger value="REFUNDED">Refunded</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      {error ? <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">{error}</div> : null}

      {loading ? (
        <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 6 }).map((_, index) => <div key={index} className="h-56 animate-pulse rounded-xl bg-muted" />)}</div>
      ) : filteredDrafts.length || filteredJobs.length ? (
        <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">
          {filteredDrafts.map((draft) => <DraftJobCard key={draft.id} draft={draft} onOpen={openDraft} onDelete={removeDraft} />)}
          {filteredJobs.map((job) => <OnchainJobCard key={job.onchain_job_id} job={job} />)}
        </div>
      ) : (
        <Card><CardContent className="flex flex-col items-center justify-center py-16 text-center"><BriefcaseBusiness className="mb-3 h-8 w-8 text-muted-foreground" /><h3 className="font-semibold">No jobs found</h3><p className="mt-1 text-sm text-muted-foreground">Create a job or change your filters.</p><Button className="mt-5" onClick={openNew}><Plus className="h-4 w-4" /> Create Job</Button></CardContent></Card>
      )}

      <CreateJobDialog open={dialogOpen} onOpenChange={setDialogOpen} initialDraft={selectedDraft} onComplete={load} />
    </div>
  );
}
