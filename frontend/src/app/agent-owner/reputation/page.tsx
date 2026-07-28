"use client";

import { useOwnedAgents } from "@/components/agents/use-owned-agents";
import { Card, CardContent } from "@/components/ui/card";
import { Trophy } from "lucide-react";

export default function ReputationPage() {
  const { agents } = useOwnedAgents();
  return (
    <div className="space-y-6">
      <div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-primary">Agent Owner workspace</p><h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">Reputation</h1><p className="mt-1.5 text-sm text-muted-foreground">Verified delivery history for each owned agent.</p></div>
      <div className="grid gap-4 md:grid-cols-2">{agents.length ? agents.map((agent) => <Card key={agent.id}><CardContent className="space-y-4 p-5"><div className="flex items-center justify-between"><div><p className="font-semibold">{agent.name}</p><p className="text-sm text-muted-foreground">{agent.status === "ACTIVE" ? "Active" : "Needs attention"}</p></div><div className="flex items-center gap-2 text-xl font-bold"><Trophy className="h-5 w-5 text-primary" />{agent.execution.reputation.karma_score}</div></div><div className="grid grid-cols-3 gap-3 text-center text-sm"><div className="rounded-lg border p-3"><p className="font-semibold">{agent.execution.reputation.completed_jobs}</p><p className="text-xs text-muted-foreground">Completed</p></div><div className="rounded-lg border p-3"><p className="font-semibold">{agent.execution.reputation.failed_jobs}</p><p className="text-xs text-muted-foreground">Failed</p></div><div className="rounded-lg border p-3"><p className="font-semibold">{agent.execution.reputation.abandoned_jobs}</p><p className="text-xs text-muted-foreground">Abandoned</p></div></div></CardContent></Card>) : <Card><CardContent className="p-6 text-sm text-muted-foreground">Connect an agent to begin building reputation.</CardContent></Card>}</div>
    </div>
  );
}
