import { WorkspaceShell } from "@/components/layout/workspace-shell";

export default function AgentOwnerLayout({ children }: { children: React.ReactNode }) {
  return <WorkspaceShell workspace="agent-owner">{children}</WorkspaceShell>;
}
