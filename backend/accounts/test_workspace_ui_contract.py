import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


FRONTEND = Path(settings.BASE_DIR).parent / "frontend" / "src"


class WorkspaceUiContractTests(SimpleTestCase):
    def test_canonical_workspace_routes_exist(self):
        routes = (
            "app/client/page.tsx",
            "app/client/jobs/page.tsx",
            "app/client/jobs/new/page.tsx",
            "app/client/github/page.tsx",
            "app/client/payments/page.tsx",
            "app/client/activity/page.tsx",
            "app/agent-owner/page.tsx",
            "app/agent-owner/agents/page.tsx",
            "app/agent-owner/assignments/page.tsx",
            "app/agent-owner/earnings/page.tsx",
            "app/agent-owner/reputation/page.tsx",
        )
        for route in routes:
            with self.subTest(route=route):
                self.assertTrue((FRONTEND / route).is_file())

    def test_navigation_is_role_specific(self):
        config = json.loads(
            (FRONTEND / "config/workspaces.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            [item["title"] for item in config["client"]["navigation"]],
            [
                "Overview",
                "Jobs",
                "Create Job",
                "GitHub",
                "Wallet & Transactions",
                "Settings",
            ],
        )
        self.assertEqual(
            [item["title"] for item in config["agent-owner"]["navigation"]],
            ["Overview", "Agents", "Earnings", "Settings"],
        )
        client_urls = " ".join(item["url"] for item in config["client"]["navigation"])
        owner_urls = " ".join(item["url"] for item in config["agent-owner"]["navigation"])
        self.assertNotIn("/agent-owner", client_urls)
        self.assertNotIn("/client", owner_urls)

    def test_account_actions_are_not_duplicated(self):
        """Profile and Log out are permanent footer rows; Log out is not duplicated.

        Both actions used to sit behind a dropdown on the sidebar user row,
        with a second Log out in the top bar. Settings is also a discoverable
        navigation alias for the shared profile.
        """
        nav_user = (FRONTEND / "components/layout/nav-user.tsx").read_text(encoding="utf-8")
        self.assertIn("profileHref(workspace)", nav_user)
        self.assertIn(">Profile<", nav_user)
        self.assertIn("logout()", nav_user)
        self.assertNotIn("DropdownMenu", nav_user)

        header = (FRONTEND / "components/layout/header.tsx").read_text(encoding="utf-8")
        self.assertNotIn("logout", header)

        config = json.loads(
            (FRONTEND / "config/workspaces.json").read_text(encoding="utf-8")
        )
        for workspace in ("client", "agent-owner"):
            titles = [item["title"] for item in config[workspace]["navigation"]]
            self.assertIn("Settings", titles)
            self.assertNotIn("Profile", titles)

    def test_profile_pages_share_one_view(self):
        """Client and Agent Owner must not drift into two different profiles."""
        for route in ("app/client/settings/page.tsx", "app/agent-owner/settings/page.tsx"):
            with self.subTest(route=route):
                source = (FRONTEND / route).read_text(encoding="utf-8")
                self.assertIn("ProfileView", source)

    def test_profile_does_not_repeat_wallet_balance_or_github_panel(self):
        """Profile shows account facts; management lives on its own surfaces."""
        view = (FRONTEND / "components/profile/profile-view.tsx").read_text(encoding="utf-8")
        self.assertNotIn("GitHubAppConnection", view)
        self.assertNotIn("usdc_balance", view)

    def test_dual_role_switcher_uses_the_same_authenticated_account(self):
        sidebar = (FRONTEND / "components/layout/app-sidebar.tsx").read_text(encoding="utf-8")
        self.assertIn('me?.capabilities?.includes("CLIENT")', sidebar)
        self.assertIn('me.capabilities.includes("AGENT_OWNER")', sidebar)
        self.assertIn('href="/client"', sidebar)
        self.assertIn('href="/agent-owner"', sidebar)
        self.assertNotIn("/login", sidebar)

    def test_workspace_layouts_enforce_capabilities(self):
        shell = (FRONTEND / "components/layout/workspace-shell.tsx").read_text(encoding="utf-8")
        self.assertIn('client: "CLIENT"', shell)
        self.assertIn('"agent-owner": "AGENT_OWNER"', shell)
        self.assertIn('router.replace("/workspace")', shell)

    def test_old_dashboard_routes_redirect_to_canonical_workspaces(self):
        redirects = {
            "app/dashboard/jobs/page.tsx": "/client/jobs",
            "app/dashboard/agents/page.tsx": "/agent-owner/agents",
            "app/dashboard/agents/new/page.tsx": "/agent-owner/agents/new",
        }
        for route, destination in redirects.items():
            with self.subTest(route=route):
                source = (FRONTEND / route).read_text(encoding="utf-8")
                self.assertIn(destination, source)
        # `/dashboard` now defers to the shared chooser instead of branching on
        # capabilities itself, so the destination no longer depends on which
        # surface runs its effect first.
        dashboard = (FRONTEND / "app/dashboard/page.tsx").read_text(encoding="utf-8")
        self.assertIn("resolveAuthDestination(me.capabilities)", dashboard)

    def test_agent_technical_identifiers_are_collapsed(self):
        details = (FRONTEND / "components/agents/hosted-runtime-card.tsx").read_text(encoding="utf-8")
        summary = details.index("Technical details")
        for label in (
            "Runtime ID",
            "Protocol version",
            "Last heartbeat",
            "Signing fingerprint",
            "Full wallet address",
            "Internal connection state",
        ):
            self.assertGreater(details.index(label), summary)
