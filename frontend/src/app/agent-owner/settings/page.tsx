"use client";

import { ProfileView } from "@/components/profile/profile-view";

/**
 * Agent Owner Profile.
 *
 * The route stays `/agent-owner/settings` so existing links keep working;
 * only the label changed to "Profile". It renders the same view as the client
 * side, which is what keeps the two workspaces consistent.
 */
export default function AgentOwnerProfilePage() {
  return <ProfileView workspace="agent-owner" />;
}
