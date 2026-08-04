from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from workers.hosted_agent_connection import (
    HostedAgentConnectionError,
    connect_hosted_agent,
)
from workers.models import WorkerAgent


class Command(BaseCommand):
    help = (
        "Create or reconnect the Veyra-managed independent verifier agent using "
        "a one-time link from the separate verifier runtime."
    )

    def add_arguments(self, parser):
        parser.add_argument("--name", default="CodeSentinel Python Verifier")
        parser.add_argument("--slug", default="codesentinel-python-verifier")
        parser.add_argument("--connection-link", default="")
        parser.add_argument("--model", default="")

    def handle(self, *args, **options):
        name = str(options["name"] or "CodeSentinel Python Verifier").strip()
        slug = slugify(str(options["slug"] or name))[:80]
        connection_link = str(options.get("connection_link") or "").strip()
        if not connection_link:
            connection_link = input(
                "Paste the verifier runtime connection link from port 9200: "
            ).strip()
        if not connection_link:
            raise CommandError("No verifier runtime connection link was supplied.")

        with transaction.atomic():
            verifier, created = WorkerAgent.objects.get_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "description": (
                        "Independently reviews exact worker commits, reruns tests, "
                        "checks acceptance criteria, and signs structured verdicts."
                    ),
                    "owner_type": WorkerAgent.OwnerType.VEYRA,
                    "owner_user": None,
                    "agent_role": WorkerAgent.AgentRole.VERIFIER,
                    "status": WorkerAgent.Status.PROFILE_READY,
                    "specialisation": WorkerAgent.Specialisation.TESTING_QA,
                    "languages": ["Python", "JavaScript"],
                    "frameworks": ["Flask", "FastAPI", "Django"],
                    "testing_tools": ["Pytest", "GitHub Actions"],
                    "task_types": ["Code review", "Security review", "Verification"],
                    "skills": [
                        "Python",
                        "JavaScript",
                        "Flask",
                        "FastAPI",
                        "Django",
                        "Pytest",
                        "GitHub Actions",
                        "Code review",
                        "Security review",
                        "Verification",
                    ],
                    "engine_provider": WorkerAgent.EngineProvider.CUSTOM,
                    "engine_model": str(options.get("model") or "zai-org/glm-5.2"),
                    "auto_claim_enabled": False,
                    "discovery_enabled": False,
                    "maximum_active_jobs": 1,
                    "maximum_execution_minutes": 30,
                    "public_repositories_only": False,
                    "protected_paths": [".env", ".git", ".github/workflows"],
                },
            )
            if not created:
                verifier.name = name
                verifier.agent_role = WorkerAgent.AgentRole.VERIFIER
                verifier.owner_type = WorkerAgent.OwnerType.VEYRA
                verifier.owner_user = None
                verifier.auto_claim_enabled = False
                verifier.discovery_enabled = False
                verifier.save()

        try:
            result = connect_hosted_agent(
                worker=verifier,
                connection_link=connection_link,
                expected_role="VERIFIER",
            )
        except HostedAgentConnectionError as exc:
            raise CommandError(str(exc)) from exc

        verifier.refresh_from_db()
        verifier.status = WorkerAgent.Status.ACTIVE
        verifier.engine_connected = True
        verifier.engine_version = result.runtime_version
        verifier.engine_provider = WorkerAgent.EngineProvider.CUSTOM
        verifier.engine_model = result.model
        verifier.engine_last_checked_at = timezone.now()
        verifier.engine_last_error = ""
        verifier.test_assignment_passed = True
        verifier.provisioning_stage = "VERIFIER_ACTIVE"
        verifier.provisioning_error = ""
        verifier.auto_claim_enabled = False
        verifier.discovery_enabled = False
        verifier.activated_at = verifier.activated_at or timezone.now()
        verifier.save(
            update_fields=[
                "status",
                "engine_connected",
                "engine_version",
                "engine_provider",
                "engine_model",
                "engine_last_checked_at",
                "engine_last_error",
                "test_assignment_passed",
                "provisioning_stage",
                "provisioning_error",
                "auto_claim_enabled",
                "discovery_enabled",
                "activated_at",
                "updated_at",
            ]
        )

        self.stdout.write(self.style.SUCCESS("Independent verifier agent connected."))
        self.stdout.write(f"Name: {verifier.name}")
        self.stdout.write(f"Agent ID: {verifier.id}")
        self.stdout.write(f"Runtime ID: {result.runtime_id}")
        self.stdout.write(f"Provider: {result.provider}")
        self.stdout.write(f"Model: {result.model}")
        self.stdout.write("Role: VERIFIER")
        self.stdout.write("Status: ACTIVE")
        self.stdout.write(
            "The verifier has no worker auto-claim permission and receives read-only repository credentials."
        )
