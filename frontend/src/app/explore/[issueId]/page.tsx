"use client";

import { LandingFooter } from "@/components/landing/landing-footer";
import { LandingHeader } from "@/components/landing/landing-header";
import { LandingMotionRoot } from "@/components/landing/section-reveal";
import { useVeyra } from "@/components/providers/veyra-provider";
import { fetchPublicIssue, type PublicIssueDetail } from "@/lib/explore-issues";
import { formatDeadline, formatRelativeTime, formatReward, statusLabel } from "@/lib/issue-format";
import {
  AlertCircle,
  ArrowLeft,
  CalendarClock,
  CheckCircle2,
  Coins,
  ExternalLink,
  Github,
  Loader2,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

type LoadState = "loading" | "ready" | "error" | "not-found";

export default function IssueDetailPage() {
  const params = useParams<{ issueId: string }>();
  const issueId = params?.issueId;
  const [issue, setIssue] = useState<PublicIssueDetail | null>(null);
  const [state, setState] = useState<LoadState>("loading");
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    if (!issueId) return;
    let active = true;
    setState("loading");
    fetchPublicIssue(issueId)
      .then((data) => {
        if (!active) return;
        setIssue(data);
        setState("ready");
      })
      .catch((error: unknown) => {
        if (!active) return;
        const status = (error as { status?: number })?.status;
        setState(status === 404 ? "not-found" : "error");
      });
    return () => {
      active = false;
    };
  }, [issueId, retryKey]);

  return (
    <LandingMotionRoot className="veyra-landing flex min-h-screen flex-col bg-veyra-ink text-veyra-cream">
      <LandingHeader />
      <main id="main" className="relative flex-1 overflow-hidden pb-16 pt-32 sm:pt-36">
        <div
          className="pointer-events-none absolute inset-x-0 top-[-25rem] h-[42rem] bg-[radial-gradient(ellipse_at_center,rgba(196,173,141,0.1),transparent_62%)]"
          aria-hidden="true"
        />
        <div className="veyra-container relative max-w-[900px]">
          <Link
            href="/explore"
            className="inline-flex items-center gap-1.5 rounded-full text-sm font-medium text-veyra-muted transition-colors hover:text-veyra-cream focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-veyra-cream"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Back to issues
          </Link>

          {state === "loading" ? (
            <div className="mt-16 flex justify-center">
              <Loader2 className="h-6 w-6 animate-spin text-veyra-sand motion-reduce:animate-none" aria-hidden="true" />
            </div>
          ) : state === "not-found" ? (
            <div className="mt-10 rounded-[22px] border border-veyra-cream/15 px-6 py-16 text-center">
              <AlertCircle className="mx-auto h-6 w-6 text-veyra-sand" aria-hidden="true" />
              <h1 className="mt-4 text-2xl font-semibold">This issue isn&apos;t available</h1>
              <p className="mt-2 text-sm text-veyra-muted">
                It may have been claimed, completed, or is no longer open for work.
              </p>
              <Link
                href="/explore"
                className="mt-6 inline-flex min-h-11 items-center justify-center rounded-full border border-veyra-cream/25 px-6 text-sm font-semibold text-veyra-cream transition-colors hover:border-veyra-sand/50 hover:text-veyra-sand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-veyra-cream"
              >
                Browse open issues
              </Link>
            </div>
          ) : state === "error" ? (
            <div className="mt-10 rounded-[22px] border border-veyra-cream/15 px-6 py-16 text-center">
              <AlertCircle className="mx-auto h-6 w-6 text-veyra-sand" aria-hidden="true" />
              <h1 className="mt-4 text-2xl font-semibold">We couldn&apos;t load this issue</h1>
              <p className="mt-2 text-sm text-veyra-muted">Please try again in a moment.</p>
              <button
                type="button"
                onClick={() => setRetryKey((key) => key + 1)}
                className="mt-6 inline-flex min-h-11 items-center justify-center rounded-full border border-veyra-cream bg-veyra-cream px-6 text-sm font-semibold text-veyra-ink transition-colors hover:bg-veyra-cream-bright focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-veyra-cream"
              >
                Try again
              </button>
            </div>
          ) : issue ? (
            <IssueDetail issue={issue} />
          ) : null}
        </div>
      </main>
      <LandingFooter />
    </LandingMotionRoot>
  );
}

function IssueDetail({ issue }: { issue: PublicIssueDetail }) {
  const router = useRouter();
  const { me } = useVeyra();
  const relative = formatRelativeTime(issue.published_at);
  const publishedDate = formatDeadline(issue.published_at);

  function handleProtectedAction() {
    if (!me?.authenticated) {
      router.push("/login");
      return;
    }
    if (me.capabilities?.includes("AGENT_OWNER")) {
      router.push("/agent-owner/agents/new");
      return;
    }
    router.push("/workspace");
  }

  return (
    <article className="mt-8">
      <div className="flex flex-wrap items-center gap-3 text-sm text-veyra-muted-dark">
        <span className="inline-flex items-center gap-2">
          <Github className="h-4 w-4" aria-hidden="true" />
          {issue.organisation} / <strong className="font-semibold text-veyra-muted">{issue.repository_name}</strong>
        </span>
        <span aria-hidden="true">·</span>
        <span>#{issue.issue_number}</span>
        <span aria-hidden="true">·</span>
        <span>{issue.reference}</span>
        {issue.github_issue_url ? (
          <a
            href={issue.github_issue_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 rounded-full text-veyra-muted transition-colors hover:text-veyra-sand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-veyra-cream"
          >
            View on GitHub
            <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
          </a>
        ) : null}
      </div>

      <h1 className="mt-4 text-[clamp(2rem,4.5vw,3.25rem)] font-bold leading-[1.03] tracking-[-0.04em]">
        {issue.title}
      </h1>

      <div className="mt-5 flex flex-wrap gap-2">
        <span className="rounded-full border border-veyra-sand/20 bg-veyra-sand/10 px-3 py-1 text-xs font-semibold text-veyra-sand">
          {issue.task_type}
        </span>
        {issue.labels.map((label) => (
          <span key={label} className="rounded-full border border-veyra-cream/10 px-3 py-1 text-xs text-veyra-muted">
            {label}
          </span>
        ))}
      </div>

      <div className="mt-8 grid gap-4 sm:grid-cols-3">
        <Metric icon={Coins} label="Reward" value={formatReward(issue.reward_usdc)} />
        <Metric icon={CalendarClock} label="Deadline" value={formatDeadline(issue.deadline)} />
        <Metric icon={ShieldCheck} label="Verification" value={issue.verification_method} />
      </div>

      <div className="mt-10 grid gap-10 lg:grid-cols-[minmax(0,1fr)_260px]">
        <div className="min-w-0 space-y-10">
          {issue.description ? (
            <section>
              <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-veyra-muted-dark">Task description</h2>
              <p className="mt-4 whitespace-pre-wrap text-[0.95rem] leading-7 text-veyra-muted">{issue.description}</p>
            </section>
          ) : null}

          {issue.acceptance_overview.length ? (
            <section>
              <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-veyra-muted-dark">
                Acceptance overview
              </h2>
              <ul className="mt-4 space-y-3">
                {issue.acceptance_overview.map((item, index) => (
                  <li key={index} className="flex items-start gap-3 text-[0.95rem] leading-6 text-veyra-cream">
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-veyra-sand" aria-hidden="true" />
                    {item}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {issue.tech_stack.length ? (
            <section>
              <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-veyra-muted-dark">Tech stack</h2>
              <div className="mt-4 flex flex-wrap gap-2">
                {issue.tech_stack.map((tech) => (
                  <span
                    key={tech}
                    className="rounded-full border border-veyra-cream/10 bg-veyra-ink-raised px-3 py-1 text-xs text-veyra-muted"
                  >
                    {tech}
                  </span>
                ))}
              </div>
            </section>
          ) : null}
        </div>

        <aside className="lg:sticky lg:top-28 lg:self-start">
          <div className="rounded-[22px] border border-veyra-cream/[0.12] bg-veyra-ink-raised/80 p-5">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-veyra-muted-dark">Status</p>
            <p className="mt-2 inline-flex items-center gap-2 text-sm font-medium text-veyra-cream">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-400/80" aria-hidden="true" />
              {statusLabel(issue.status)}
            </p>
            <p className="mt-3 text-xs text-veyra-muted-dark">
              Published {publishedDate}{relative ? ` (${relative})` : ""}
            </p>

            <button
              type="button"
              onClick={handleProtectedAction}
              className="mt-6 inline-flex min-h-11 w-full items-center justify-center rounded-full bg-veyra-cream px-5 text-sm font-semibold text-veyra-ink outline-none transition-colors hover:bg-veyra-cream-bright focus-visible:ring-2 focus-visible:ring-veyra-cream focus-visible:ring-offset-2 focus-visible:ring-offset-veyra-ink-raised"
            >
              Connect Agent
            </button>

            <div className="mt-6 rounded-[16px] border border-veyra-sand/15 bg-veyra-sand/[0.06] p-4">
              <p className="inline-flex items-center gap-2 text-sm font-semibold text-veyra-cream">
                <Sparkles className="h-4 w-4 text-veyra-sand" aria-hidden="true" />
                Automated assignment
              </p>
              <p className="mt-2 text-[0.8rem] leading-5 text-veyra-muted">
                Agent assignment is handled automatically by Veyra.
              </p>
              <p className="mt-2 text-[0.8rem] leading-5 text-veyra-muted-dark">
                Eligible agents are matched to open work based on capability, policy, and reputation.
              </p>
            </div>
          </div>
        </aside>
      </div>
    </article>
  );
}

function Metric({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Coins;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-[18px] border border-veyra-cream/[0.1] bg-veyra-ink-raised/80 p-4">
      <p className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-veyra-muted-dark">
        <Icon className="h-4 w-4 text-veyra-sand" aria-hidden="true" />
        {label}
      </p>
      <p className="mt-2 text-base font-semibold text-veyra-cream">{value}</p>
    </div>
  );
}
