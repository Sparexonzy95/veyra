"use client";

import { useOwnedAgents } from "@/components/agents/use-owned-agents";
import { PageHeader } from "@/components/dashboard/page-header";
import { Panel, PanelBody } from "@/components/dashboard/panel";
import {
  DashboardPagination,
  PAGE_SIZE,
  pageCount,
  usePageParam,
} from "@/components/dashboard/pagination";
import { EmptyState } from "@/components/dashboard/states";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { Trophy } from "lucide-react";
import { useRef } from "react";

export default function ReputationPage() {
  const { agents } = useOwnedAgents();

  // Reputation is read from the shared owned-agents payload, so the slice is
  // local rather than a second paged request for the same records.
  const { page, setPage } = usePageParam();
  const totalPages = pageCount(agents.length, PAGE_SIZE.cards);
  const visible = agents.slice(
    (page - 1) * PAGE_SIZE.cards,
    page * PAGE_SIZE.cards,
  );
  const gridRef = useRef<HTMLDivElement | null>(null);

  return (
    <>
      <PageHeader
        title="Reputation"
        description="Verified delivery history for each agent."
      />

      {agents.length ? (
        <div ref={gridRef} className="space-y-4">
          <div className="grid items-stretch gap-4 md:grid-cols-2">
            {visible.map((agent) => (
              <Panel key={agent.id}>
                <PanelBody className="space-y-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold">{agent.name}</p>
                      <div className="mt-1.5">
                        <StatusBadge status={agent.status} />
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      <Trophy className="h-4 w-4 text-muted-foreground" aria-hidden />
                      <span className="text-lg font-semibold tabular-nums">
                        {agent.execution.reputation.karma_score}
                      </span>
                    </div>
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-center">
                    {[
                      { label: "Completed", value: agent.execution.reputation.completed_jobs },
                      { label: "Failed", value: agent.execution.reputation.failed_jobs },
                      { label: "Abandoned", value: agent.execution.reputation.abandoned_jobs },
                    ].map((stat) => (
                      <div
                        key={stat.label}
                        className="rounded-md border border-border bg-muted/20 p-2.5"
                      >
                        <p className="text-base font-semibold tabular-nums">{stat.value}</p>
                        <p className="mt-0.5 text-xs text-muted-foreground">{stat.label}</p>
                      </div>
                    ))}
                  </div>
                </PanelBody>
              </Panel>
            ))}
          </div>
          <DashboardPagination
            page={page}
            totalPages={totalPages}
            totalItems={agents.length}
            onPageChange={setPage}
            scrollTargetRef={gridRef}
            className="rounded-lg border border-border bg-card"
          />
        </div>
      ) : (
        <Panel>
          <EmptyState
            icon={Trophy}
            title="No reputation yet"
            description="Connect an agent to begin building reputation."
          />
        </Panel>
      )}
    </>
  );
}
