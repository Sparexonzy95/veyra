"use client";

import { useOwnedAgents } from "@/components/agents/use-owned-agents";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CircleDollarSign } from "lucide-react";

export default function EarningsPage() {
  const { agents } = useOwnedAgents();
  const total = agents.reduce((sum, agent) => sum + Number(agent.execution.reputation.total_earned_usdc || 0), 0);
  return (
    <div className="space-y-6">
      <div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-primary">Agent Owner workspace</p><h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">Earnings</h1><p className="mt-1.5 text-sm text-muted-foreground">Verified USDC earnings across your agents.</p></div>
      <Card><CardHeader><CardTitle className="flex items-center gap-2"><CircleDollarSign className="h-5 w-5" /> Total earned</CardTitle></CardHeader><CardContent><p className="text-3xl font-bold">{total.toFixed(2)} USDC</p><p className="mt-1 text-sm text-muted-foreground">Settled after independent verification.</p></CardContent></Card>
      <div className="grid gap-4 md:grid-cols-2">{agents.map((agent) => <Card key={agent.id}><CardContent className="flex items-center justify-between p-5"><div><p className="font-semibold">{agent.name}</p><p className="text-sm text-muted-foreground">{agent.execution.reputation.completed_jobs} completed jobs</p></div><p className="font-semibold">{agent.execution.reputation.total_earned_usdc} USDC</p></CardContent></Card>)}</div>
    </div>
  );
}
