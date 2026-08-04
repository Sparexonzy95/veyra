from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from workers.models import WorkerAgent


DEFAULT_SKILLS = [
    "Python",
    "Flask",
    "Django",
    "Pytest",
    "TypeScript",
    "Next.js",
]


class Command(BaseCommand):
    help = "Create or update the Veyra-owned worker profile without storing secrets."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="veyra-code-agent")
        parser.add_argument("--name", default="Veyra Code Agent")
        parser.add_argument("--model", default="zai-org/glm-5.2")
        parser.add_argument("--minimum-budget", default="1.000000")
        parser.add_argument("--maximum-active-jobs", type=int, default=1)
        parser.add_argument(
            "--skills",
            nargs="+",
            default=DEFAULT_SKILLS,
            help="Space-separated worker skills.",
        )

    def handle(self, *args, **options):
        try:
            minimum_budget = Decimal(options["minimum_budget"])
        except Exception as exc:
            raise CommandError("--minimum-budget must be a valid decimal amount.") from exc

        defaults = {
            "name": options["name"],
            "description": (
                "Veyra-operated autonomous coding worker for public GitHub "
                "repositories using a fork-and-pull-request workflow."
            ),
            "owner_type": WorkerAgent.OwnerType.VEYRA,
            "owner_user": None,
            "status": WorkerAgent.Status.PROFILE_READY,
            "skills": options["skills"],
            "minimum_budget_usdc": minimum_budget,
            "maximum_active_jobs": options["maximum_active_jobs"],
            "repository_strategy": WorkerAgent.RepositoryStrategy.FORK_PR,
            "engine_provider": WorkerAgent.EngineProvider.OPENCODE,
            "engine_model": options["model"],
            "wallet_blockchain": "ARC-TESTNET",
            "wallet_account_type": "SCA",
        }

        worker, created = WorkerAgent.objects.update_or_create(
            slug=options["slug"],
            defaults=defaults,
        )
        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{action} worker profile: {worker.name}"))
        self.stdout.write(f"Worker ID: {worker.id}")
        self.stdout.write(f"Status: {worker.status}")
        self.stdout.write(f"Skills: {', '.join(worker.skills)}")
        self.stdout.write("Secrets stored in database: none")