import type { WorkspaceKind } from "@/components/layout/app-sidebar";

/**
 * Where Profile lives for a workspace.
 *
 * The underlying routes are still `/client/settings` and
 * `/agent-owner/settings`. Only the label changed to "Profile"; renaming the
 * directories would invalidate existing links and bookmarks for a cosmetic
 * gain, so the brief's rename is applied to what the user reads.
 *
 * Having a single helper means the sidebar footer, the GitHub return path
 * and anything added later cannot disagree about the path.
 */
export function profileHref(workspace: WorkspaceKind) {
  return workspace === "client" ? "/client/settings" : "/agent-owner/settings";
}
