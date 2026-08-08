"use client";

import {
  DesktopIssueFilters,
  MobileIssueFilters,
  SORT_OPTIONS,
  type ExploreFilters,
} from "@/components/explore/issue-filters";
import { IssueCard, IssueCardSkeleton } from "@/components/explore/issue-card";
import { LandingFooter } from "@/components/landing/landing-footer";
import { LandingHeader } from "@/components/landing/landing-header";
import { LandingMotionRoot } from "@/components/landing/section-reveal";
import {
  fetchPublicIssueFacets,
  fetchPublicIssues,
  ISSUES_PER_PAGE,
  type IssueSort,
  type PublicIssue,
  type PublicIssueFacets,
} from "@/lib/explore-issues";
import { AlertCircle, ChevronLeft, ChevronRight } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

type LoadState = "loading" | "ready" | "error";

function parseSort(value: string | null): IssueSort {
  return SORT_OPTIONS.some((option) => option.value === value) ? (value as IssueSort) : "newest";
}

function parseReward(value: string): number | undefined {
  if (!value.trim()) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : undefined;
}

function ExploreContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const headingRef = useRef<HTMLDivElement>(null);
  const didMount = useRef(false);

  const urlPage = Math.max(1, Number(searchParams.get("page")) || 1);
  const urlSearch = searchParams.get("search") ?? "";
  const urlFilters: ExploreFilters = {
    project: searchParams.get("project") ?? "",
    taskType: searchParams.get("task_type") ?? "",
    label: searchParams.get("label") ?? "",
    techStack: searchParams.get("tech_stack") ?? "",
    minReward: searchParams.get("min_reward") ?? "",
    maxReward: searchParams.get("max_reward") ?? "",
    verification: searchParams.get("verification") ?? "",
    sort: parseSort(searchParams.get("sort")),
  };

  const [searchInput, setSearchInput] = useState(urlSearch);
  const [rewardInputs, setRewardInputs] = useState({
    minReward: urlFilters.minReward,
    maxReward: urlFilters.maxReward,
  });
  const [issues, setIssues] = useState<PublicIssue[]>([]);
  const [facets, setFacets] = useState<PublicIssueFacets | null>(null);
  const [facetsFailed, setFacetsFailed] = useState(false);
  const [count, setCount] = useState(0);
  const [state, setState] = useState<LoadState>("loading");
  const [retryKey, setRetryKey] = useState(0);

  const updateParams = useCallback((updates: Record<string, string | number | undefined>, resetPage = true) => {
    const params = new URLSearchParams(searchParams.toString());
    Object.entries(updates).forEach(([key, value]) => {
      if (value === undefined || value === "" || (key === "sort" && value === "newest")) params.delete(key);
      else params.set(key, String(value));
    });
    if (resetPage) params.delete("page");
    const query = params.toString();
    router.push(query ? `/explore?${query}` : "/explore", { scroll: false });
  }, [router, searchParams]);

  useEffect(() => setSearchInput(urlSearch), [urlSearch]);
  useEffect(() => {
    setRewardInputs({ minReward: urlFilters.minReward, maxReward: urlFilters.maxReward });
  }, [urlFilters.minReward, urlFilters.maxReward]);

  useEffect(() => {
    if (!didMount.current) {
      didMount.current = true;
      return;
    }
    const handle = window.setTimeout(() => {
      const updates: Record<string, string> = {};
      if (searchInput !== urlSearch) updates.search = searchInput.trim();
      if (rewardInputs.minReward !== urlFilters.minReward) updates.min_reward = rewardInputs.minReward;
      if (rewardInputs.maxReward !== urlFilters.maxReward) updates.max_reward = rewardInputs.maxReward;
      if (Object.keys(updates).length) updateParams(updates);
    }, 350);
    return () => window.clearTimeout(handle);
  }, [searchInput, rewardInputs, urlSearch, urlFilters.minReward, urlFilters.maxReward, updateParams]);

  useEffect(() => {
    let active = true;
    fetchPublicIssueFacets()
      .then((data) => {
        if (!active) return;
        setFacets(data);
        setFacetsFailed(false);
      })
      .catch(() => {
        if (active) setFacetsFailed(true);
      });
    return () => { active = false; };
  }, [retryKey]);

  useEffect(() => {
    let active = true;
    setState("loading");
    fetchPublicIssues({
      search: urlSearch,
      project: urlFilters.project,
      taskType: urlFilters.taskType,
      label: urlFilters.label,
      techStack: urlFilters.techStack,
      minReward: parseReward(urlFilters.minReward),
      maxReward: parseReward(urlFilters.maxReward),
      verification: urlFilters.verification,
      sort: urlFilters.sort,
      page: urlPage,
    }).then((data) => {
      if (!active) return;
      setIssues(data.results);
      setCount(data.count);
      setState("ready");
    }).catch(() => {
      if (active) setState("error");
    });
    return () => { active = false; };
  }, [urlSearch, urlFilters.project, urlFilters.taskType, urlFilters.label,
    urlFilters.techStack, urlFilters.minReward, urlFilters.maxReward,
    urlFilters.verification, urlFilters.sort, urlPage, retryKey]);

  const filterValues = { ...urlFilters, ...rewardInputs };
  const activeCount = [urlSearch, urlFilters.project, urlFilters.taskType, urlFilters.label,
    urlFilters.techStack, urlFilters.minReward, urlFilters.maxReward, urlFilters.verification].filter(Boolean).length;
  const totalPages = Math.max(1, Math.ceil(count / ISSUES_PER_PAGE));

  const changeFilter = useCallback((key: keyof ExploreFilters, value: string) => {
    if (key === "minReward" || key === "maxReward") {
      setRewardInputs((current) => ({ ...current, [key]: value }));
      return;
    }
    const paramKeys: Record<Exclude<keyof ExploreFilters, "minReward" | "maxReward">, string> = {
      project: "project", taskType: "task_type", label: "label", techStack: "tech_stack",
      verification: "verification", sort: "sort",
    };
    updateParams({ [paramKeys[key]]: value });
  }, [updateParams]);

  const clearFilters = useCallback(() => {
    setSearchInput("");
    setRewardInputs({ minReward: "", maxReward: "" });
    router.push("/explore", { scroll: false });
  }, [router]);

  const goToPage = useCallback((page: number) => {
    updateParams({ page: page > 1 ? page : undefined }, false);
    requestAnimationFrame(() => headingRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }, [updateParams]);

  const filterProps = {
    facets, facetsFailed, search: searchInput, values: filterValues, activeCount,
    onSearchChange: setSearchInput, onChange: changeFilter, onClear: clearFilters,
  };

  return (
    <LandingMotionRoot className="veyra-landing flex min-h-screen flex-col bg-veyra-ink text-veyra-cream">
      <LandingHeader />
      <main id="main" className="relative flex-1 overflow-hidden pb-16 pt-32 sm:pt-36">
        <div className="pointer-events-none absolute inset-x-0 top-[-25rem] h-[42rem] bg-[radial-gradient(ellipse_at_center,rgba(196,173,141,0.1),transparent_62%)]" aria-hidden="true" />
        <div className="veyra-container relative max-w-[1180px]">
          <div ref={headingRef} className="scroll-mt-28">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-veyra-sand">Explore issues</p>
            <h1 className="mt-3 max-w-[780px] text-balance text-[clamp(2rem,4.5vw,3.5rem)] font-bold leading-[1.03] tracking-[-0.04em]">Open software work on Veyra</h1>
            <p className="mt-4 max-w-[620px] text-pretty text-base leading-7 text-veyra-muted">Browse verified, funded tasks published by Veyra clients and maintainers.</p>
          </div>

          <div className="mt-8 flex items-center justify-between gap-4 border-b border-veyra-cream/10 pb-5">
            <p className="text-sm font-medium text-veyra-muted" aria-live="polite">
              {state === "loading" ? "Loading issues..." : `${count} open ${count === 1 ? "issue" : "issues"}`}
            </p>
            <div className="hidden items-center gap-2 sm:flex">
              <label htmlFor="result-sort" className="text-sm text-veyra-muted-dark">Sort by</label>
              <select id="result-sort" value={urlFilters.sort} onChange={(event) => changeFilter("sort", event.target.value)} className="h-10 rounded-xl border border-veyra-cream/10 bg-veyra-ink-raised px-3 text-sm text-veyra-cream outline-none focus-visible:border-veyra-sand/50 focus-visible:ring-2 focus-visible:ring-veyra-sand/20">
                {SORT_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </div>
          </div>

          <div className="mt-7">
            <MobileIssueFilters {...filterProps} />
            <div className="grid items-start gap-7 lg:grid-cols-[minmax(0,1fr)_280px]">
              <section aria-label="Open issues" className="min-w-0">
                {state === "loading" ? <IssueGridSkeleton /> : state === "error" ? (
                  <ErrorState onRetry={() => setRetryKey((key) => key + 1)} />
                ) : issues.length === 0 ? <EmptyState onClear={clearFilters} /> : (
                  <div className="grid gap-5 md:grid-cols-2">{issues.map((issue) => <IssueCard key={issue.reference} issue={issue} />)}</div>
                )}
                {state === "ready" && issues.length > 0 && totalPages > 1 ? <Pagination current={urlPage} total={totalPages} onChange={goToPage} /> : null}
              </section>
              <DesktopIssueFilters {...filterProps} />
            </div>
          </div>
        </div>
      </main>
      <LandingFooter />
    </LandingMotionRoot>
  );
}

function Pagination({ current, total, onChange }: { current: number; total: number; onChange: (page: number) => void }) {
  const pages = useMemo(() => Array.from(new Set([1, total, current, current - 1, current + 1])).filter((page) => page >= 1 && page <= total).sort((a, b) => a - b), [current, total]);
  return (
    <nav className="mt-10 flex flex-wrap items-center justify-center gap-1.5" aria-label="Pagination">
      <PageButton disabled={current <= 1} onClick={() => onChange(current - 1)} label="Previous"><ChevronLeft className="h-4 w-4" aria-hidden="true" /></PageButton>
      {pages.map((page, index) => (
        <span key={page} className="flex items-center gap-1.5">
          {pages[index - 1] !== undefined && page - pages[index - 1] > 1 ? <span className="px-1 text-veyra-muted-dark">...</span> : null}
          <button type="button" onClick={() => onChange(page)} aria-current={page === current ? "page" : undefined} className={page === current ? "inline-flex h-10 min-w-10 items-center justify-center rounded-full bg-veyra-cream px-3 text-sm font-semibold text-veyra-ink" : "inline-flex h-10 min-w-10 items-center justify-center rounded-full border border-veyra-cream/12 px-3 text-sm font-medium text-veyra-cream outline-none transition-colors hover:border-veyra-sand/40 focus-visible:ring-2 focus-visible:ring-veyra-cream"}>{page}</button>
        </span>
      ))}
      <PageButton disabled={current >= total} onClick={() => onChange(current + 1)} label="Next"><ChevronRight className="h-4 w-4" aria-hidden="true" /></PageButton>
    </nav>
  );
}

function PageButton({ disabled, onClick, label, children }: { disabled: boolean; onClick: () => void; label: string; children: React.ReactNode }) {
  return <button type="button" onClick={onClick} disabled={disabled} aria-label={label} title={label} className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-veyra-cream/12 text-veyra-cream outline-none transition-colors hover:border-veyra-sand/40 disabled:pointer-events-none disabled:opacity-40 focus-visible:ring-2 focus-visible:ring-veyra-cream">{children}</button>;
}

function IssueGridSkeleton() {
  return <div className="grid gap-5 md:grid-cols-2">{Array.from({ length: ISSUES_PER_PAGE }).map((_, index) => <IssueCardSkeleton key={index} />)}</div>;
}

function EmptyState({ onClear }: { onClear: () => void }) {
  return <div className="rounded-[22px] border border-veyra-cream/12 bg-veyra-ink-raised/40 px-6 py-16 text-center"><p className="text-lg font-semibold text-veyra-cream">No open issues match these filters.</p><button type="button" onClick={onClear} className="mt-6 inline-flex min-h-11 items-center justify-center rounded-full border border-veyra-cream/25 px-6 text-sm font-semibold text-veyra-cream outline-none transition-colors hover:border-veyra-sand/50 hover:text-veyra-sand focus-visible:ring-2 focus-visible:ring-veyra-cream">Clear filters</button></div>;
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return <div className="rounded-[22px] border border-veyra-cream/12 bg-veyra-ink-raised/40 px-6 py-16 text-center"><AlertCircle className="mx-auto h-6 w-6 text-veyra-sand" aria-hidden="true" /><p className="mt-4 text-lg font-semibold text-veyra-cream">We couldn&apos;t load issues.</p><p className="mt-2 text-sm text-veyra-muted">Please try again in a moment.</p><button type="button" onClick={onRetry} className="mt-6 inline-flex min-h-11 items-center justify-center rounded-full bg-veyra-cream px-6 text-sm font-semibold text-veyra-ink outline-none transition-colors hover:bg-veyra-cream-bright focus-visible:ring-2 focus-visible:ring-veyra-cream focus-visible:ring-offset-2 focus-visible:ring-offset-veyra-ink">Try again</button></div>;
}

export default function ExplorePage() {
  return <Suspense fallback={null}><ExploreContent /></Suspense>;
}