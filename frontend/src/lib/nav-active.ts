/**
 * Which navigation item is active, for exactly one item at a time.
 *
 * The previous rule was `pathname.startsWith(itemPath)` with an exact-match
 * special case for the workspace home. Two things went wrong with it:
 *
 *   1. Every item was judged independently, so nothing stopped two of them
 *      from answering "yes" for the same URL.
 *   2. The query string was discarded before comparing. "Available Work"
 *      (`/agent-owner/assignments?view=available`) and "Assignments"
 *      (`/agent-owner/assignments`) are the same route with different views,
 *      so once the query was dropped they became indistinguishable and both
 *      highlighted.
 *
 * This resolver picks a single winner instead:
 *
 *   - a candidate matches on an exact path, or on a `/`-delimited descendant
 *     of it, so `/agent-owner/agents/123` matches `/agent-owner/agents` while
 *     `/agent-owner/agents-archive` does not;
 *   - the workspace home is the exception: it matches only itself. It is a
 *     page, not a section, and every route in the workspace sits under it, so
 *     letting it match descendants makes it the fallback highlight for any
 *     page that has no nav entry of its own — Profile, for instance, which
 *     would then light up in the footer *and* light Overview up in the nav;
 *   - the longest matching path wins, so a detail route activates its own
 *     section rather than the workspace home;
 *   - between candidates that tie on path, the one whose query requirements
 *     the current URL actually satisfies wins.
 *
 * No `includes`, and no bare `startsWith` without a segment boundary.
 */

export type NavCandidate = {
  /** The href as configured, query string included. */
  url: string;
};

/** Path and required query pairs for one candidate. */
function parse(url: string) {
  const [path, query = ""] = url.split("?");
  const required = new URLSearchParams(query);
  return { path, required: [...required.entries()] };
}

/** True when `pathname` is the path itself or a descendant segment of it. */
function pathMatches(pathname: string, path: string) {
  if (pathname === path) return true;
  return pathname.startsWith(`${path}/`);
}

/**
 * Index of the single active item, or -1 when none apply.
 *
 * `currentQuery` accepts anything URLSearchParams-like, which is what
 * `useSearchParams()` returns. `homePath` is the workspace root, which is
 * matched exactly rather than as a prefix; -1 is a legitimate answer for a
 * page that is reached from somewhere other than the nav.
 */
export function resolveActiveNavIndex(
  items: readonly NavCandidate[],
  pathname: string,
  currentQuery?: Pick<URLSearchParams, "get">,
  homePath?: string,
): number {
  let winner = -1;
  let winningPathLength = -1;
  let winningQueryScore = -1;

  items.forEach((item, index) => {
    const { path, required } = parse(item.url);
    const matched =
      path === homePath ? pathname === path : pathMatches(pathname, path);
    if (!matched) return;

    // Every configured query pair has to be present, or this is a different
    // view of the route and must not claim the highlight.
    const satisfied = required.every(
      ([key, value]) => currentQuery?.get(key) === value,
    );
    if (!satisfied) return;

    const queryScore = required.length;

    // Longest path first, then the more specific query. Strictly greater, so
    // the earliest item in the configured order keeps a genuine tie.
    if (
      path.length > winningPathLength ||
      (path.length === winningPathLength && queryScore > winningQueryScore)
    ) {
      winner = index;
      winningPathLength = path.length;
      winningQueryScore = queryScore;
    }
  });

  return winner;
}
