import { GitHubAppConnection } from "@/components/jobs/github-app-connection";

export default function ClientGitHubPage() {
  return (
    <div className="space-y-6">
      <div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-primary">Client workspace</p><h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">GitHub</h1><p className="mt-1.5 text-sm text-muted-foreground">Choose the repositories Veyra may use for your jobs.</p></div>
      <GitHubAppConnection returnPath="/client/github?github=connected" />
    </div>
  );
}
