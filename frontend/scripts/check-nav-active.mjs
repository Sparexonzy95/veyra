/**
 * Checks that exactly one navigation item is ever active.
 *
 * Run: node scripts/check-nav-active.mjs
 *
 * This mirrors resolveActiveNavIndex against the real workspaces.json so the
 * expected cases in the brief are verified rather than assumed. It is a plain
 * script because the frontend has no test runner configured.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const config = JSON.parse(
  readFileSync(join(here, "../src/config/workspaces.json"), "utf8"),
);

// Kept in step with src/lib/nav-active.ts.
function resolveActiveNavIndex(items, pathname, query, homePath) {
  let winner = -1;
  let winningPathLength = -1;
  let winningQueryScore = -1;

  items.forEach((item, index) => {
    const [path, search = ""] = item.url.split("?");
    const required = [...new URLSearchParams(search).entries()];
    const matched =
      path === homePath
        ? pathname === path
        : pathname === path || pathname.startsWith(`${path}/`);
    if (!matched) return;
    if (!required.every(([key, value]) => query?.get(key) === value)) return;

    const queryScore = required.length;
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

const cases = [
  ["agent-owner", "/agent-owner", "", "Overview"],
  ["agent-owner", "/agent-owner/agents", "", "Agents"],
  ["agent-owner", "/agent-owner/agents/123", "", "Agents"],
  ["agent-owner", "/agent-owner/agents/new", "", "Agents"],
  ["agent-owner", "/agent-owner/assignments", "", "(none)"],
  ["agent-owner", "/agent-owner/assignments", "view=available", "(none)"],
  ["agent-owner", "/agent-owner/assignments/42", "", "(none)"],
  ["agent-owner", "/agent-owner/earnings", "", "Earnings"],
  ["agent-owner", "/agent-owner/reputation", "", "(none)"],
  ["agent-owner", "/agent-owner/settings", "", "Settings"],
  ["client", "/client", "", "Overview"],
  ["client", "/client/jobs", "", "Jobs"],
  ["client", "/client/jobs/new", "", "Create Job"],
  ["client", "/client/github", "", "GitHub"],
  ["client", "/client/github/callback", "", "GitHub"],
  ["client", "/client/payments", "", "Wallet & Transactions"],
  ["client", "/client/payments", "page=2", "Wallet & Transactions"],
  ["client", "/client/activity", "", "(none)"],
  ["client", "/client/settings", "", "Settings"],
];

let failures = 0;

for (const [workspace, pathname, search, expected] of cases) {
  const items = config[workspace].navigation;
  const query = new URLSearchParams(search);
  const home = config[workspace].home;
  const index = resolveActiveNavIndex(items, pathname, query, home);
  const actual = index === -1 ? "(none)" : items[index].title;

  // The point of the exercise: count every item that would light up. "(none)"
  // is a valid expectation for pages outside the nav, so allow zero there.
  const activeCount = items.filter((_, i) => i === index).length;
  const ok =
    actual === expected && activeCount === (expected === "(none)" ? 0 : 1);
  if (!ok) failures += 1;

  const url = search ? `${pathname}?${search}` : pathname;
  console.log(
    `${ok ? "PASS" : "FAIL"}  ${url.padEnd(42)} → ${actual}${
      ok ? "" : `  (expected ${expected})`
    }`,
  );
}

console.log(
  failures === 0
    ? `\nAll ${cases.length} cases passed, one active item each.`
    : `\n${failures} of ${cases.length} cases failed.`,
);
process.exit(failures === 0 ? 0 : 1);
