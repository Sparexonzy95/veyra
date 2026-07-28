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
            ["Overview", "Jobs", "Create Job", "GitHub", "Payments", "Activity", "Settings"],
        )
        self.assertEqual(
            [item["title"] for item in config["agent-owner"]["navigation"]],
            ["Overview", "My Agents", "Available Work", "Assignments", "Earnings", "Reputation", "Settings"],
        )
        client_urls = " ".join(item["url"] for item in config["client"]["navigation"])
        owner_urls = " ".join(item["url"] for item in config["agent-owner"]["navigation"])
        self.assertNotIn("/agent-owner", client_urls)
        self.assertNotIn("/client", owner_urls)

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
        dashboard = (FRONTEND / "app/dashboard/page.tsx").read_text(encoding="utf-8")
        self.assertIn('router.replace("/client")', dashboard)
        self.assertIn('router.replace("/agent-owner")', dashboard)

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
