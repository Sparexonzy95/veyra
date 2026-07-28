import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { JobDraft, JobSummary } from "@/types/veyra";
import { Calendar, CircleDollarSign, Github, Trash2 } from "lucide-react";
import Link from "next/link";
import { JobStatusBadge } from "@/components/jobs/job-status-badge";

function formatDate(value: string | number) {
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleDateString();
}

export function OnchainJobCard({ job }: { job: JobSummary }) {
  return (
    <Card className="group cursor-pointer bg-card/90 transition-all hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md">
      <CardContent className="p-5">
        <div className="flex h-full flex-col gap-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <Link href={`/client/jobs/${job.onchain_job_id}`} className="line-clamp-2 font-semibold hover:text-primary">
                {job.title}
              </Link>
              <p className="mt-1 truncate text-xs text-muted-foreground">{job.github_issue_url.replace("https://github.com/", "")}</p>
            </div>
            <JobStatusBadge status={job.client_status} />
          </div>
          <div className="grid gap-2 text-sm">
            <div className="flex items-center gap-2">
              <CircleDollarSign className="h-4 w-4 text-muted-foreground" />
              <span className="font-medium">{job.budget_usdc} USDC</span>
            </div>
          </div>
          <div className="mt-auto flex items-center justify-between border-t border-muted pt-3">
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              <Calendar className="h-3 w-3" />
              <span>Due {formatDate(job.expires_at)}</span>
            </div>
            <Button variant="ghost" size="sm" asChild>
              <Link href={`/client/jobs/${job.onchain_job_id}`}>View Job</Link>
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export function DraftJobCard({
  draft,
  onOpen,
  onDelete,
}: {
  draft: JobDraft;
  onOpen: (draft: JobDraft) => void;
  onDelete: (draft: JobDraft) => void;
}) {
  const canDelete = draft.status === "DRAFT" || draft.status === "READY";
  return (
    <Card className="group bg-card/90 transition-all hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md">
      <CardContent className="p-5">
        <div className="flex h-full flex-col gap-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <button type="button" className="line-clamp-2 text-left font-semibold hover:text-primary" onClick={() => onOpen(draft)}>
                {draft.issue_title || "New GitHub job"}
              </button>
              <p className="mt-1 truncate text-xs text-muted-foreground">Draft · {draft.repository_owner}/{draft.repository_name}</p>
            </div>
            <JobStatusBadge status={draft.status} />
          </div>
          <div className="grid gap-2 text-sm">
            <div className="flex items-center gap-2">
              <CircleDollarSign className="h-4 w-4 text-muted-foreground" />
              <span className="font-medium">{draft.budget_usdc} USDC</span>
            </div>
            <div className="flex items-center gap-2 text-muted-foreground">
              <Github className="h-4 w-4" />
              <span className="truncate">{draft.github_issue_url.replace("https://github.com/", "")}</span>
            </div>
          </div>
          <div className="mt-auto flex items-center justify-between border-t border-muted pt-3">
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              <Calendar className="h-3 w-3" />
              <span>Due {formatDate(draft.deadline)}</span>
            </div>
            <div className="flex items-center gap-1">
              {canDelete ? (
                <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => onDelete(draft)}>
                  <Trash2 className="h-3 w-3" />
                </Button>
              ) : null}
              <Button variant="ghost" size="sm" onClick={() => onOpen(draft)}>
                {draft.status === "FUNDING" || draft.status === "LOCKED" ? "Resume" : "Open"}
              </Button>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
