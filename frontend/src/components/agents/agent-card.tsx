import { AgentStatusBadge } from "@/components/agents/agent-status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card";
import type { AgentSummary } from "@/types/veyra";
import { Bot, ChevronRight } from "lucide-react";
import Link from "next/link";

/**
 * Compact summary of one agent.
 *
 * The card answers three questions and nothing more: can Veyra reach it, is it
 * allowed to take work, and is it busy. Provider readiness, earnings and the
 * assignment count were removed — earnings duplicated the Earnings page,
 * "Assignments" restated the same `active_jobs` number already shown as
 * workload, and provider readiness is a diagnostic that only matters once you
 * are looking at one agent. All of it remains on the agent detail page.
 *
 * Three rows in a single column, so the metrics never wrap into a second
 * column and every card in the grid keeps the same height.
 */
export function AgentCard({ agent }: { agent: AgentSummary }) {
  return (
    <Card className="flex h-full flex-col">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Bot className="h-4 w-4" />
            </div>
            <h3 className="truncate text-sm font-semibold">{agent.name}</h3>
          </div>
          <AgentStatusBadge status={agent.status} />
        </div>
      </CardHeader>

      <CardContent className="pb-4">
        {/* A description list rather than divs: each value is bound to its
            label for assistive technology. */}
        <dl className="space-y-1.5 text-sm">
          <Row
            label="Connection"
            value={agent.runtime.connected ? "Connected" : "Offline"}
          />
          <Row
            label="Qualification"
            value={agent.test_assignment_passed ? "Qualified" : "In progress"}
          />
          <Row
            label="Workload"
            value={`${agent.execution.active_jobs}/${agent.execution.capacity}`}
          />
        </dl>
      </CardContent>

      {/* mt-auto pins the action to the bottom, so buttons line up across the
          row even when a name wraps differently. */}
      <CardFooter className="mt-auto pt-0">
        <Button variant="outline" size="sm" className="w-full" asChild>
          <Link href={`/agent-owner/agents/${agent.id}`}>
            Open Agent
            <ChevronRight className="h-4 w-4" />
          </Link>
        </Button>
      </CardFooter>
    </Card>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="truncate text-right font-medium">{value}</dd>
    </div>
  );
}
