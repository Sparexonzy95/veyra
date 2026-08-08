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
import { EmptyState, ErrorState } from "@/components/dashboard/states";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { AlertTriangle, ListChecks, Search } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useMemo, useRef } from "react";

export default function AssignmentsPage() {
  const { agents, error } = useOwnedAgents();
  const available = useSearchParams().get("view") === "available";
  const assignments = useMemo(
    () =>
      agents.flatMap((agent) =>
        agent.execution.recent_assignments
          .filter((item) => item !== null)
          .map((item) => ({ ...item!, ownerAgentName: agent.name })),
      ),
    [agents],
  );

  // Assignments arrive nested inside the owner's agents payload, so there is
  // no assignment endpoint to page against; the slice is local over an
  // already-bounded "recent assignments" set.
  const { page, setPage } = usePageParam();
  const totalPages = pageCount(assignments.length, PAGE_SIZE.cards);
  const visible = assignments.slice(
    (page - 1) * PAGE_SIZE.cards,
    page * PAGE_SIZE.cards,
  );
  const gridRef = useRef<HTMLDivElement | null>(null);

  return (
    <>
      <PageHeader
        title={available ? "Available Work" : "Assignments"}
        description={
          available
            ? "Funded work is matched to eligible agents automatically."
            : "Current and recent work across your agents."
        }
      />

      {error ? <ErrorState message={error} /> : null}

      {available ? (
        /* Read-only by design: matching is automatic, so there is nothing to
           claim here. The panel used to spell out the policy and capacity
           rules in a paragraph, which restated the description above it. The
           page header carries that sentence now. */
        <Panel>
          <EmptyState
            icon={Search}
            title="No work is currently waiting for assignment."
          />
        </Panel>
      ) : assignments.length ? (
        <div ref={gridRef} className="space-y-4">
          <div className="grid items-stretch gap-4 md:grid-cols-2">
            {visible.map((assignment) => (
              <Panel key={assignment.id}>
                <PanelBody className="space-y-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold">{assignment.job_title}</p>
                      <p className="mt-0.5 truncate text-xs text-muted-foreground">
                        {assignment.ownerAgentName}
                      </p>
                    </div>
                    <StatusBadge status={assignment.stage_label} />
                  </div>
                  <p className="truncate text-xs text-muted-foreground">
                    {assignment.repository} · Issue #{assignment.issue_number}
                  </p>
                  {assignment.attention_required ? (
                    <p className="flex items-start gap-1.5 text-xs text-amber-600 dark:text-amber-400">
                      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                      {assignment.attention_message}
                    </p>
                  ) : null}
                </PanelBody>
              </Panel>
            ))}
          </div>
          <DashboardPagination
            page={page}
            totalPages={totalPages}
            totalItems={assignments.length}
            onPageChange={setPage}
            scrollTargetRef={gridRef}
            className="rounded-lg border border-border bg-card"
          />
        </div>
      ) : (
        <Panel>
          <EmptyState
            icon={ListChecks}
            title="No assignments yet"
            description="Assignments appear when an active agent matches funded work."
          />
        </Panel>
      )}
    </>
  );
}
