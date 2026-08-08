"use client";

import { AgentCard } from "@/components/agents/agent-card";
import { PageHeader } from "@/components/dashboard/page-header";
import { Panel } from "@/components/dashboard/panel";
import {
  DashboardPagination,
  PAGE_SIZE,
  pageCount,
  usePageParam,
} from "@/components/dashboard/pagination";
import { EmptyState, ErrorState, LoadingCards } from "@/components/dashboard/states";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";
import type { PaginatedAgents } from "@/types/veyra";
import { Bot, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

export default function AgentsPage() {
  const [data, setData] = useState<PaginatedAgents | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { page, setPage } = usePageParam();

  // `/api/v1/agents/` is a DRF ViewSet, so this is real server-side paging:
  // the page number goes to the API and only that page is fetched. The
  // polling refresh below re-requests the current page, not page 1, so a
  // ten-second tick cannot yank the user back to the start of the list.
  const load = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true);
      try {
        setData(
          await apiFetch<PaginatedAgents>(
            `/api/v1/agents/?page=${page}&page_size=${PAGE_SIZE.cards}`,
          ),
        );
        setError(null);
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Agents could not be loaded.");
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [page],
  );

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load(true);
    }, 10000);
    return () => window.clearInterval(timer);
  }, [load]);

  const agents = data?.results ?? [];
  const totalPages = pageCount(data?.count ?? 0, PAGE_SIZE.cards);
  const gridRef = useRef<HTMLDivElement | null>(null);

  return (
    <>
      <PageHeader
        title="Agents"
        description="Connect, qualify and manage your Agent Starters."
        actions={
          <Button size="sm" asChild>
            <Link href="/agent-owner/agents/new">
              <Plus className="mr-1.5 h-4 w-4" /> Create Agent
            </Link>
          </Button>
        }
      />

      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}

      {/* The stat band that used to sit here duplicated the Agent summary on
          the Overview page. It also could not survive server-side paging:
          "Connected" and "Qualified" were counted from the loaded page, so
          they would have silently meant "on this page" once the list was cut
          to six. Overview owns the summary; this page owns the list, and the
          honest total is the count in the pagination bar. */}
      {loading ? (
        <div className="grid items-stretch gap-4 md:grid-cols-2 xl:grid-cols-3">
          <LoadingCards count={3} />
        </div>
      ) : agents.length ? (
        <div ref={gridRef} className="space-y-4">
          <div className="grid items-stretch gap-4 md:grid-cols-2 xl:grid-cols-3">
            {agents.map((agent) => (
              <AgentCard key={agent.id} agent={agent} />
            ))}
          </div>
          <DashboardPagination
            page={page}
            totalPages={totalPages}
            totalItems={data?.count}
            onPageChange={setPage}
            scrollTargetRef={gridRef}
            className="rounded-lg border border-border bg-card"
          />
        </div>
      ) : (
        <Panel>
          <EmptyState
            icon={Bot}
            title="Create your first agent"
            description="Download the Agent Starter, host it, then paste its connection URL to test and connect."
            action={
              <Button size="sm" asChild>
                <Link href="/agent-owner/agents/new">
                  <Plus className="mr-1.5 h-4 w-4" /> Create Agent
                </Link>
              </Button>
            }
          />
        </Panel>
      )}
    </>
  );
}
