"use client";

import { CreateJobDialog } from "@/components/jobs/create-job-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ArrowLeft, BriefcaseBusiness } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

export default function CreateJobPage() {
  const router = useRouter();
  const [open, setOpen] = useState(true);

  return (
    <div className="space-y-6">
      <Button variant="ghost" asChild className="px-0"><Link href="/client/jobs"><ArrowLeft className="h-4 w-4" /> Back to Jobs</Link></Button>
      <div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-primary">Client workspace</p><h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">Create Job</h1><p className="mt-1.5 text-sm text-muted-foreground">Turn an approved GitHub issue into protected, funded work.</p></div>
      <Card><CardContent className="flex flex-col items-center py-14 text-center"><BriefcaseBusiness className="mb-3 h-9 w-9 text-primary" /><h2 className="text-lg font-semibold">Job builder</h2><p className="mt-2 max-w-lg text-sm text-muted-foreground">Review repository access, acceptance criteria, budget and verification before Circle asks you to approve funding.</p><Button className="mt-6" onClick={() => setOpen(true)}>Open job builder</Button></CardContent></Card>
      <CreateJobDialog
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) router.push("/client/jobs");
        }}
        onComplete={() => router.push("/client/jobs")}
      />
    </div>
  );
}
