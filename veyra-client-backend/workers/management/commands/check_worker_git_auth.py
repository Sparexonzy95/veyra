from django.core.management.base import BaseCommand, CommandError

from workers.github_bot import check_github_bot
from workers.models import WorkerAgent
from workers.test_assignment import (
    GitHubWorkerClient,
    WorkerTestAssignmentError,
    verify_noninteractive_git_credentials,
)


class Command(BaseCommand):
    help = (
        "Verify that Git can use the worker token without opening a browser or "
        "requesting terminal input. No repository write is performed."
    )

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="veyra-code-agent")

    def handle(self, *args, **options):
        try:
            worker = WorkerAgent.objects.get(slug=options["slug"])
        except WorkerAgent.DoesNotExist as exc:
            raise CommandError(
                f"Worker '{options['slug']}' does not exist."
            ) from exc

        try:
            result = check_github_bot(expected_username=worker.github_username)
            github = GitHubWorkerClient(username=worker.github_username)
            verify_noninteractive_git_credentials(
                username=worker.github_username,
                token=github.token,
            )
        except WorkerTestAssignmentError as exc:
            raise CommandError(f"[{exc.stage}] {exc}") from exc
        except RuntimeError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS("Non-interactive Git authentication passed.")
        )
        self.stdout.write(f"GitHub account: {result.login}")
        self.stdout.write("Browser prompts: disabled")
        self.stdout.write("Git Credential Manager: bypassed for worker pushes")
        self.stdout.write("Credential source: temporary GIT_ASKPASS helper")
        self.stdout.write("GitHub token stored in database: no")
        self.stdout.write("No repository was modified and no push was performed.")
