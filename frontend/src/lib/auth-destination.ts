/**
 * Single source of truth for where an authenticated user belongs.
 *
 * Before this existed, `processLogin` sent every authenticated user to
 * `/workspace` while `/dashboard` resolved `/client` and `/agent-owner`
 * separately, so the destination depended on which surface happened to run
 * its effect first. Both now call `resolveAuthDestination`.
 *
 * The rules match the behaviour `/dashboard` already implemented, so this
 * centralises the existing product decision rather than inventing a new one.
 */

export type Capability = string;

/** Never a public marketing route: `/` must not be a post-auth destination. */
export const ROLE_SELECTION_PATH = "/workspace";

export function resolveAuthDestination(
  capabilities: Capability[] | null | undefined,
): string {
  const list = capabilities ?? [];
  const hasClient = list.includes("CLIENT");
  const hasAgentOwner = list.includes("AGENT_OWNER");

  // Both capabilities: the workspace switcher is the canonical landing spot,
  // because picking one for the user would be a guess.
  if (hasClient && hasAgentOwner) return ROLE_SELECTION_PATH;
  if (hasClient) return "/client";
  if (hasAgentOwner) return "/agent-owner";

  // Authenticated but no capability yet: `/workspace` hosts the existing
  // "How do you want to use Veyra?" chooser.
  return ROLE_SELECTION_PATH;
}

/**
 * Accept only same-origin absolute paths.
 *
 * Rejects protocol-relative (`//evil.com`) and absolute URLs so a crafted
 * `?returnTo=` cannot bounce a freshly authenticated user off-site, and
 * rejects `/` so the public landing page can never be reinstated as the
 * post-authentication destination through a query parameter.
 */
export function safeReturnPath(value: string | null | undefined): string | null {
  if (!value) return null;
  if (!value.startsWith("/")) return null;
  if (value.startsWith("//")) return null;
  if (value.startsWith("/\\")) return null;

  const path = value.split(/[?#]/)[0];
  if (path === "/" || path === "") return null;
  if (path === "/login") return null;

  return value;
}
