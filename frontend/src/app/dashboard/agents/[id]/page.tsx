import { redirect } from "next/navigation";

export default async function LegacyAgentRedirect({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  redirect(`/agent-owner/agents/${id}`);
}
