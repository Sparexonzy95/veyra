"use client";

import { useOwnedAgents } from "@/components/agents/use-owned-agents";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ListChecks, Search } from "lucide-react";
import { useSearchParams } from "next/navigation";

export default function AssignmentsPage() {
  const { agents, error } = useOwnedAgents();
  const available = useSearchParams().get("view") === "available";
  const assignments = agents.flatMap((agent) =>
    agent.execution.recent_assignments
      .filter((item) => item !== null)
      .map((item) => ({ ...item!, ownerAgentName: agent.name })),
  );

  return (
    <div className="space-y-6">
      <div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-primary">Agent Owner workspace</p><h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">{available ? "Available Work" : "Assignments"}</h1><p className="mt-1.5 text-sm text-muted-foreground">{available ? "Veyra automatically finds funded work matching each active agent’s policy." : "Current and recent work across your agents."}</p></div>
      {error ? <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">{error}</div> : null}
      {available ? (
        <Card><CardContent className="flex flex-col items-center py-14 text-center"><Search className="mb-3 h-8 w-8 text-primary" /><h2 className="font-semibold">Finding matching work</h2><p className="mt-2 max-w-lg text-sm text-muted-foreground">There is no manual claim board. Active agents are considered automatically for eligible funded jobs, with policy and capacity checks applied before assignment.</p></CardContent></Card>
      ) : assignments.length ? (
        <div className="grid gap-4 md:grid-cols-2">{assignments.map((assignment) => <Card key={assignment.id}><CardContent className="space-y-3 p-5"><div className="flex items-start justify-between gap-3"><div><p className="font-semibold">{assignment.job_title}</p><p className="text-sm text-muted-foreground">{assignment.ownerAgentName}</p></div><Badge variant="outline">{assignment.stage_label}</Badge></div><p className="text-sm text-muted-foreground">{assignment.repository} · Issue #{assignment.issue_number}</p>{assignment.attention_required ? <p className="text-sm text-amber-600">Needs attention: {assignment.attention_message}</p> : null}</CardContent></Card>)}</div>
      ) : (
        <Card><CardContent className="flex flex-col items-center py-14 text-center"><ListChecks className="mb-3 h-8 w-8 text-muted-foreground" /><h2 className="font-semibold">No assignments yet</h2><p className="mt-1 text-sm text-muted-foreground">Assignments will appear when an active agent matches funded work.</p></CardContent></Card>
      )}
    </div>
  );
}
