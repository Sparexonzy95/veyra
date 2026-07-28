import { AgentStatusBadge } from "@/components/agents/agent-status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card";
import type { AgentSummary } from "@/types/veyra";
import { Bot, ChevronRight } from "lucide-react";
import Link from "next/link";

export function AgentCard({ agent }: { agent: AgentSummary }) {
  return (
    <Card className="flex h-full flex-col overflow-hidden">
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Bot className="h-5 w-5" />
            </div>
            <h3 className="truncate text-base font-semibold">{agent.name}</h3>
          </div>
          <AgentStatusBadge status={agent.status} />
        </div>
      </CardHeader>
      <CardContent className="mt-auto grid gap-3 text-sm sm:grid-cols-2">
        <Metric label="Connection" value={agent.runtime.connected ? "Connected" : "Offline"} />
        <Metric label="Provider readiness" value={agent.runtime.provider_ready ? "Ready" : "Needs attention"} />
        <Metric label="Qualification" value={agent.test_assignment_passed ? "Qualified" : "In progress"} />
        <Metric label="Current workload" value={`${agent.execution.active_jobs}/${agent.execution.capacity}`} />
        <Metric label="Earnings" value={`${agent.execution.reputation.total_earned_usdc} USDC`} />
        <Metric label="Assignments" value={String(agent.execution.active_jobs)} />
      </CardContent>
      <CardFooter className="pt-5">
        <Button variant="outline" className="w-full" asChild>
          <Link href={`/agent-owner/agents/${agent.id}`}>Open agent <ChevronRight className="h-4 w-4" /></Link>
        </Button>
      </CardFooter>
    </Card>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="flex items-center justify-between gap-3"><span className="text-muted-foreground">{label}</span><span className="text-right">{value}</span></div>;
}
