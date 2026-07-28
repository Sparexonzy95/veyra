import { redirect } from "next/navigation";

export default function LegacyNewAgentRedirect() {
  redirect("/agent-owner/agents/new");
}
