import { WorkspaceShell } from "@/components/layout/workspace-shell";

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  return <WorkspaceShell workspace="client">{children}</WorkspaceShell>;
}
