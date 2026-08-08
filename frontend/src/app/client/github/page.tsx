import { PageHeader } from "@/components/dashboard/page-header";
import { GitHubAppConnection } from "@/components/jobs/github-app-connection";

export default function ClientGitHubPage() {
  return (
    <>
      <PageHeader
        title="GitHub"
        description="Manage repositories available to Veyra."
      />
      <GitHubAppConnection returnPath="/client/github?github=connected" />
    </>
  );
}
