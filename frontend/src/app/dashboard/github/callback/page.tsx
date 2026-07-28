import { redirect } from "next/navigation";

export default function LegacyGitHubCallbackRedirect() {
  redirect("/client/github/callback");
}
