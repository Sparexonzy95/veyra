from django.core.management.base import BaseCommand, CommandError

from workers.github_bot import (
    GitHubBotConnectionError,
    connect_worker_github,
)
from workers.models import WorkerAgent


class Command(BaseCommand):
    help = "Verify and connect the dedicated GitHub bot to a Veyra worker."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="veyra-code-agent")
        parser.add_argument(
            "--username",
            default=None,
            help=(
                "Expected GitHub username. Defaults to GITHUB_BOT_USERNAME "
                "from the backend .env."
            ),
        )

    def handle(self, *args, **options):
        try:
            worker = WorkerAgent.objects.get(slug=options["slug"])
        except WorkerAgent.DoesNotExist as exc:
            raise CommandError(
                f"Worker '{options['slug']}' does not exist."
            ) from exc

        try:
            result = connect_worker_github(
                worker,
                expected_username=options["username"],
            )
        except GitHubBotConnectionError as exc:
            raise CommandError(str(exc)) from exc

        worker.refresh_from_db()

        self.stdout.write(self.style.SUCCESS("Connected GitHub bot."))
        self.stdout.write(f"Worker: {worker.name}")
        self.stdout.write(f"Status: {worker.status}")
        self.stdout.write(f"GitHub username: {worker.github_username}")
        self.stdout.write(f"GitHub account ID: {result.github_user_id}")
        self.stdout.write(f"Account type: {result.account_type}")
        self.stdout.write(f"Checked at: {result.checked_at}")
        self.stdout.write("GitHub token stored in database: no")
