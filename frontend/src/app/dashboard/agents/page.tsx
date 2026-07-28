import { redirect } from "next/navigation";

export default function LegacyAgentsRedirect() {
  redirect("/agent-owner/agents");
}
