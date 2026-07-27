import { AgentStatusBadge } from "@/components/agents/agent-status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card";
import type { AgentSummary } from "@/types/veyra";
import { Bot, ChevronRight, Github, Radio, Wallet } from "lucide-react";
import Link from "next/link";

function shortAddress(address: string) {
  return address ? `${address.slice(0, 6)}…${address.slice(-4)}` : "Not created";
}

export function AgentCard({ agent }: { agent: AgentSummary }) {
  const capabilities = [
    ...agent.languages,
    ...agent.frameworks,
    ...agent.testing_tools,
    ...agent.task_types,
  ].slice(0, 6);

  return (
    <Card className="flex h-full flex-col overflow-hidden">
      <CardHeader className="space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Bot className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <h3 className="truncate text-base font-semibold">{agent.name}</h3>
              <p className="truncate text-sm text-muted-foreground">
                {agent.specialisation.replaceAll("_", " ").toLowerCase()}
              </p>
            </div>
          </div>
          <AgentStatusBadge status={agent.status} />
        </div>
        <p className="line-clamp-2 min-h-10 text-sm text-muted-foreground">
          {agent.description || "No description added yet."}
        </p>
        <div className="flex flex-wrap gap-2">
          {capabilities.map((capability) => (
            <Badge key={capability} variant="outline">
              {capability}
            </Badge>
          ))}
        </div>
      </CardHeader>
      <CardContent className="mt-auto space-y-3 text-sm">
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-2 text-muted-foreground">
            <Radio className="h-4 w-4" /> Runtime
          </span>
          <span>
            {agent.runtime.runtime_mode === "VEYRA_HOSTED"
              ? agent.runtime.connected
                ? "Hosted · Ready"
                : "Hosted · Preparing"
              : agent.runtime.status.replaceAll("_", " ").toLowerCase().replace(/^./, (value) => value.toUpperCase())}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-2 text-muted-foreground">
            <Github className="h-4 w-4" /> GitHub
          </span>
          <span>{agent.github_connected ? agent.github_username : "Not connected"}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-2 text-muted-foreground">
            <Wallet className="h-4 w-4" /> Arc wallet
          </span>
          <span>{shortAddress(agent.worker_wallet_address)}</span>
        </div>
      </CardContent>
      <CardFooter className="pt-5">
        <Button variant="outline" className="w-full" asChild>
          <Link href={`/dashboard/agents/${agent.id}`}>
            Open agent <ChevronRight className="h-4 w-4" />
          </Link>
        </Button>
      </CardFooter>
    </Card>
  );
}
