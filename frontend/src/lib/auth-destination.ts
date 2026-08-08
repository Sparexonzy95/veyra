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

/** Every successful sign-in lands on the shared, reusable workspace chooser. */
export const ROLE_SELECTION_PATH = "/workspace";

export function resolveAuthDestination(
  _capabilities: Capability[] | null | undefined,
): string {
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
