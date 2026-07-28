"use client";

import { useVeyra } from "@/components/providers/veyra-provider";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

export default function AgentOwnerSettingsPage() {
  const { me } = useVeyra();
  return (
    <div className="space-y-6">
      <div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-primary">Agent Owner workspace</p><h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">Settings</h1><p className="mt-1.5 text-sm text-muted-foreground">Account preferences for managing your agents.</p></div>
      <Card><CardHeader><CardTitle>Account</CardTitle></CardHeader><CardContent className="space-y-4"><div><p className="text-xs uppercase tracking-wide text-muted-foreground">Display name</p><p className="mt-1 font-medium">{me?.user?.display_name || "Agent Owner"}</p></div><Separator /><div><p className="text-xs uppercase tracking-wide text-muted-foreground">Email</p><p className="mt-1 font-medium">{me?.user?.email || "Not provided"}</p></div><Separator /><div><p className="text-xs uppercase tracking-wide text-muted-foreground">Workspace</p><p className="mt-1 font-medium">Agent Owner</p></div></CardContent></Card>
    </div>
  );
}
