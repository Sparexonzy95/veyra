"use client";

import { Card, CardContent } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import type { DashboardResponse } from "@/types/veyra";
import { Activity } from "lucide-react";
import { useEffect, useState } from "react";

export default function ClientActivityPage() {
  const [data, setData] = useState<DashboardResponse | null>(null);
  useEffect(() => { void apiFetch<DashboardResponse>("/api/v1/client/dashboard/").then(setData); }, []);
  return (
    <div className="space-y-6">
      <div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-primary">Client workspace</p><h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">Activity</h1><p className="mt-1.5 text-sm text-muted-foreground">Job, delivery and payment updates for your account.</p></div>
      <Card><CardContent className="divide-y p-0">{data?.notifications.length ? data.notifications.map((item) => <div key={item.id} className="flex gap-3 p-5"><Activity className="mt-0.5 h-4 w-4 text-primary" /><div><p className="font-medium">{item.title}</p><p className="mt-1 text-sm text-muted-foreground">{item.body}</p><p className="mt-2 text-xs text-muted-foreground">{new Date(item.created_at).toLocaleString()}</p></div></div>) : <p className="p-6 text-sm text-muted-foreground">No activity yet.</p>}</CardContent></Card>
    </div>
  );
}
