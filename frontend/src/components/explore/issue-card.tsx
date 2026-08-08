import type { PublicIssue } from "@/lib/explore-issues";
import { formatDeadline, formatRelativeTime, formatReward } from "@/lib/issue-format";
import { ArrowUpRight, CalendarClock, Coins, Github } from "lucide-react";
import Link from "next/link";

export function IssueCard({ issue }: { issue: PublicIssue }) {
  const relative = formatRelativeTime(issue.published_at);
  return (
    <article className="group flex h-full min-h-[210px] flex-col rounded-[18px] border border-veyra-cream/[0.12] bg-veyra-ink-raised/80 p-4 transition-[border-color,transform] duration-200 hover:-translate-y-0.5 hover:border-veyra-sand/35 motion-reduce:transform-none motion-reduce:transition-none sm:p-5">
      <div className="flex items-center justify-between gap-3 text-xs text-veyra-muted-dark">
        <span className="inline-flex min-w-0 items-center gap-2">
          <Github className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span className="truncate">
            {issue.organisation} / <strong className="font-semibold text-veyra-muted">{issue.repository_name}</strong>
          </span>
        </span>
        <span className="shrink-0">#{issue.issue_number}</span>
      </div>

      <h2 className="mt-3 line-clamp-2 text-base font-semibold leading-snug tracking-[-0.015em] text-veyra-cream sm:text-lg">
        {issue.title}
      </h2>

      <div className="mt-2.5">
        <span className="rounded-full border border-veyra-sand/20 bg-veyra-sand/10 px-2.5 py-1 text-xs font-semibold text-veyra-sand">
          {issue.task_type}
        </span>
      </div>

      <div className="mt-3 flex items-center gap-2 text-xs text-veyra-muted-dark">
        <Coins className="h-3.5 w-3.5 shrink-0 text-veyra-sand" aria-hidden="true" />
        <span className="font-semibold text-veyra-cream">{formatReward(issue.reward_usdc)}</span>
        <span aria-hidden="true">·</span>
        <CalendarClock className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span>Due {formatDeadline(issue.deadline)}</span>
      </div>

      <div className="mt-auto flex items-end justify-between gap-4 pt-4">
        <span className="text-xs text-veyra-muted-dark">{relative ? `Published ${relative}` : "Open"}</span>
        <Link
          href={`/explore/${issue.reference}`}
          aria-label={`View issue: ${issue.title}`}
          className="inline-flex items-center gap-1.5 rounded-full border border-veyra-cream/20 px-3.5 py-1.5 text-sm font-semibold text-veyra-cream outline-none transition-colors hover:border-veyra-sand/50 hover:text-veyra-sand focus-visible:ring-2 focus-visible:ring-veyra-cream"
        >
          View Issue
          <ArrowUpRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5 motion-reduce:transform-none" aria-hidden="true" />
        </Link>
      </div>
    </article>
  );
}

export function IssueCardSkeleton() {
  return (
    <div className="min-h-[210px] animate-pulse rounded-[18px] border border-veyra-cream/[0.08] bg-veyra-ink-raised/60 p-4 sm:p-5 motion-reduce:animate-none">
      <div className="flex justify-between">
        <div className="h-3 w-32 rounded bg-veyra-cream/10" />
        <div className="h-3 w-8 rounded bg-veyra-cream/10" />
      </div>
      <div className="mt-4 h-5 w-4/5 rounded bg-veyra-cream/10" />
      <div className="mt-3 h-6 w-20 rounded-full bg-veyra-cream/10" />
      <div className="mt-4 h-3 w-3/5 rounded bg-veyra-cream/10" />
      <div className="mt-6 flex justify-between">
        <div className="h-3 w-24 rounded bg-veyra-cream/10" />
        <div className="h-7 w-24 rounded-full bg-veyra-cream/10" />
      </div>
    </div>
  );
}
