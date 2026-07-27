"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { postJson } from "@/lib/api";
import { CheckCircle2, Github, Loader2, ShieldAlert } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

export default function GitHubCallbackPage() {
  const router = useRouter();
  const [state, setState] = useState<"working" | "done" | "error">("working");
  const [message, setMessage] = useState("Confirming repository access…");
  const [returnPath, setReturnPath] = useState("/dashboard/jobs");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const installationId = params.get("installation_id");
    const stateValue = params.get("state");
    if (!installationId || !stateValue) {
      setState("error");
      setMessage("GitHub returned an incomplete installation response.");
      return;
    }

    void postJson<{
      return_path: string;
      repositories: Array<{ id: string }>;
    }>("/api/v1/client/github/app/install/complete/", {
      installation_id: installationId,
      state: stateValue,
    })
      .then((result) => {
        setReturnPath(result.return_path || "/dashboard/jobs");
        setMessage(
          `GitHub connected. ${result.repositories.length} ${result.repositories.length === 1 ? "repository is" : "repositories are"} available to Veyra.`,
        );
        setState("done");
        window.setTimeout(() => router.replace(result.return_path || "/dashboard/jobs"), 1200);
      })
      .catch((error) => {
        setState("error");
        setMessage(error instanceof Error ? error.message : "GitHub connection could not be completed.");
      });
  }, [router]);

  return (
    <div className="mx-auto flex min-h-[60vh] max-w-xl items-center justify-center">
      <Card className="w-full">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Github className="h-5 w-5" /> Veyra GitHub App
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-5 text-center">
          {state === "working" ? <Loader2 className="mx-auto h-10 w-10 animate-spin text-primary" /> : null}
          {state === "done" ? <CheckCircle2 className="mx-auto h-10 w-10 text-emerald-600" /> : null}
          {state === "error" ? <ShieldAlert className="mx-auto h-10 w-10 text-destructive" /> : null}
          <p className="text-sm text-muted-foreground">{message}</p>
          {state === "error" ? (
            <Button onClick={() => router.replace(returnPath)}>Back to Veyra</Button>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
