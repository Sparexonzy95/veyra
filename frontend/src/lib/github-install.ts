/**
 * Carrying the GitHub App install handshake across the redirect to github.com
 * and back into the authenticated client workspace.
 *
 * Two separate things have to survive that round trip:
 *
 *  1. the signed `state` minted by the Veyra backend, and
 *  2. the parameters GitHub puts on the Setup URL when it sends the browser
 *     back (`installation_id`, `setup_action`, and optionally `code`).
 *
 * (2) is the part that was being lost. `/client/github/callback` renders inside
 * WorkspaceShell, which calls `router.replace("/login")` or
 * `router.replace("/workspace")` from an effect while the session is still
 * resolving. That navigation replaces the URL - query string included - and by
 * the time the callback page's own effect runs, `window.location.search` is
 * empty. The parameters were never missing from GitHub's redirect; they were
 * being thrown away on our side, a moment after arriving.
 *
 * The fix is to read the query string at module evaluation time. This module is
 * imported by the callback page, so the snapshot is taken while the document
 * URL is still the one GitHub navigated to, strictly before React mounts and
 * before any effect can call the router. The snapshot is also mirrored into
 * sessionStorage so it survives a remount if the shell does bounce the user
 * through /login and back.
 *
 * sessionStorage (not localStorage) is deliberate: everything here dies with
 * the tab rather than lingering on a shared machine.
 */

export const GITHUB_INSTALL_STATE_KEY = "veyra.github.install.state";
export const GITHUB_INSTALL_RETURN_KEY = "veyra.github.install.return";
const GITHUB_CALLBACK_SNAPSHOT_KEY = "veyra.github.callback.params";

export type GitHubCallbackParams = {
  installationId: string;
  setupAction: string;
  state: string;
  hasCode: boolean;
  /** Any query key GitHub actually sent, for diagnostics. Values are excluded. */
  presentKeys: string[];
  /** True when the URL carried no GitHub parameters at all. */
  empty: boolean;
};

const EMPTY_PARAMS: GitHubCallbackParams = {
  installationId: "",
  setupAction: "",
  state: "",
  hasCode: false,
  presentKeys: [],
  empty: true,
};

function readFromSearch(search: string): GitHubCallbackParams {
  const params = new URLSearchParams(search);
  const presentKeys = Array.from(params.keys()).sort();
  const installationId = (params.get("installation_id") || "").trim();
  const setupAction = (params.get("setup_action") || "").trim();
  const state = (params.get("state") || "").trim();
  const hasCode = Boolean((params.get("code") || "").trim());
  return {
    installationId,
    setupAction,
    state,
    hasCode,
    presentKeys,
    empty: !installationId && !setupAction && !state && !hasCode,
  };
}

/**
 * The snapshot, taken once when this module is first evaluated.
 *
 * Nothing here navigates, clears the URL, or calls the router: the parameters
 * are only copied. The address bar is left exactly as GitHub set it so the page
 * can be reloaded and the flow retried.
 */
const capturedAtLoad: GitHubCallbackParams = (() => {
  if (typeof window === "undefined") return EMPTY_PARAMS;

  const fromUrl = readFromSearch(window.location.search);
  if (!fromUrl.empty) {
    try {
      window.sessionStorage.setItem(
        GITHUB_CALLBACK_SNAPSHOT_KEY,
        JSON.stringify(fromUrl),
      );
    } catch {
      // Storage unavailable: the in-memory snapshot still covers the common case.
    }
    return fromUrl;
  }

  // The URL is already bare. If a redirect stripped it moments ago, the
  // snapshot taken on the previous evaluation is still in sessionStorage.
  try {
    const stored = window.sessionStorage.getItem(GITHUB_CALLBACK_SNAPSHOT_KEY);
    if (stored) {
      const parsed = JSON.parse(stored) as GitHubCallbackParams;
      if (parsed && typeof parsed === "object") {
        return { ...EMPTY_PARAMS, ...parsed, empty: false };
      }
    }
  } catch {
    // Unreadable or malformed: fall through to the empty result.
  }
  return fromUrl;
})();

/** The GitHub callback parameters as they arrived, before any navigation. */
export function getCapturedCallbackParams(): GitHubCallbackParams {
  return capturedAtLoad;
}

/** Drop the snapshot once the handshake has reached a final state. */
export function clearCapturedCallbackParams(): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(GITHUB_CALLBACK_SNAPSHOT_KEY);
  } catch {
    // Nothing to clean up if storage is unavailable.
  }
}

/**
 * True only for a real GitHub App *installation* URL:
 *
 *     https://github.com/apps/<slug>/installations/new?state=<signed-state>
 *
 * Anything else - an OAuth authorisation URL, a bare app page, or a relative
 * path that would navigate straight back into our own callback - is rejected,
 * because none of those flows produce an `installation_id` on the return leg.
 */
export function isGitHubInstallUrl(url: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    // Relative or malformed: never a valid destination for this flow.
    return false;
  }
  if (parsed.protocol !== "https:") return false;
  if (parsed.hostname !== "github.com" && parsed.hostname !== "www.github.com") {
    return false;
  }
  // OAuth authorisation returns `code` only, never an installation.
  if (parsed.pathname.startsWith("/login/oauth/")) return false;
  return /^\/apps\/[^/]+\/installations\/new\/?$/.test(parsed.pathname);
}

/**
 * Pull the `state` query parameter out of the install URL the backend built, so
 * a copy can be kept for the return leg. Returns an empty string if the URL is
 * unparseable or carries no state.
 */
export function extractInstallState(installUrl: string): string {
  try {
    return new URL(installUrl).searchParams.get("state") || "";
  } catch {
    return "";
  }
}

/**
 * Remember the state and the page to come back to, immediately before handing
 * the browser to GitHub. Storage failures are non-fatal: the flow still works
 * whenever GitHub returns the state on the URL itself.
 */
export function rememberInstallState(state: string, returnPath: string): void {
  if (typeof window === "undefined") return;
  try {
    if (state) window.sessionStorage.setItem(GITHUB_INSTALL_STATE_KEY, state);
    if (returnPath) window.sessionStorage.setItem(GITHUB_INSTALL_RETURN_KEY, returnPath);
  } catch {
    // Private browsing or storage quota: fall back to GitHub's own state echo.
  }
}

export function readStoredInstallState(): { state: string; returnPath: string } {
  if (typeof window === "undefined") return { state: "", returnPath: "" };
  try {
    return {
      state: window.sessionStorage.getItem(GITHUB_INSTALL_STATE_KEY) || "",
      returnPath: window.sessionStorage.getItem(GITHUB_INSTALL_RETURN_KEY) || "",
    };
  } catch {
    return { state: "", returnPath: "" };
  }
}

export function clearStoredInstallState(): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(GITHUB_INSTALL_STATE_KEY);
    window.sessionStorage.removeItem(GITHUB_INSTALL_RETURN_KEY);
  } catch {
    // Nothing to clean up if storage is unavailable.
  }
}
