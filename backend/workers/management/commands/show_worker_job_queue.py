from django.core.management.base import BaseCommand, CommandError

from workers.models import WorkerAgent, WorkerJobQueueItem


class Command(BaseCommand):
    help = "Show the worker's sanitized job discovery queue."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="veyra-code-agent")
        parser.add_argument("--status", default=None)
        parser.add_argument("--limit", type=int, default=20)

    def handle(self, *args, **options):
        try:
            worker = WorkerAgent.objects.get(slug=options["slug"])
        except WorkerAgent.DoesNotExist as exc:
            raise CommandError(f"Worker '{options['slug']}' does not exist.") from exc

        query = WorkerJobQueueItem.objects.select_related("job", "job__draft").filter(
            worker=worker
        )
        if options["status"]:
            status = options["status"].upper()
            if status not in WorkerJobQueueItem.Status.values:
                raise CommandError(
                    "Unknown status. Valid values: "
                    + ", ".join(WorkerJobQueueItem.Status.values)
                )
            query = query.filter(status=status)

        limit = max(1, min(options["limit"], 100))
        items = list(query[:limit])

        self.stdout.write(f"Worker: {worker.name}")
        self.stdout.write(f"Worker status: {worker.status}")
        self.stdout.write(f"Discovery enabled: {str(worker.discovery_enabled).lower()}")
        self.stdout.write(f"Queue items shown: {len(items)}")

        if not items:
            self.stdout.write("Queue is empty.")
            return

        for item in items:
            draft = item.job.draft
            self.stdout.write("")
            self.stdout.write(f"Queue item: {item.id}")
            self.stdout.write(f"Status: {item.status}")
            self.stdout.write(f"Arc job: #{item.job.onchain_job_id}")
            self.stdout.write(
                f"Repository: {draft.repository_owner}/{draft.repository_name}"
            )
            self.stdout.write(f"Issue: #{draft.issue_number} — {draft.issue_title}")
            self.stdout.write(f"Budget: {draft.budget_usdc} USDC")
            self.stdout.write(f"Onchain status: {item.onchain_status or '-'}")
            self.stdout.write(
                f"GitHub freshness: {item.github_freshness_code or 'not checked'}"
            )
            github = item.github_snapshot if isinstance(item.github_snapshot, dict) else {}
            self.stdout.write(f"GitHub issue state: {github.get('issue_state') or '-'}")
            self.stdout.write(
                f"Existing worker PR: {github.get('existing_pull_request_url') or '-'}"
            )
            self.stdout.write(
                f"Existing worker branch: {github.get('existing_branch') or '-'}"
            )
            self.stdout.write(f"Eligibility: {item.eligibility_code or '-'}")
            self.stdout.write(f"Detail: {item.eligibility_detail or '-'}")
            self.stdout.write(f"Priority score: {item.priority_score}")
            self.stdout.write(
                "Required stack: "
                + (", ".join(item.required_skills) or "not detected")
            )
            self.stdout.write(
                "Matched skills: "
                + (", ".join(item.matched_skills) or "none")
            )
            self.stdout.write(f"Last checked: {item.last_checked_at or '-'}")
            self.stdout.write(f"Queued at: {item.queued_at or '-'}")
            self.stdout.write(
                f"Claim attempts: {item.claim_attempt_count}"
            )
            self.stdout.write(
                f"Circle claim transaction: {item.claim_circle_transaction_id or '-'}"
            )
            self.stdout.write(
                f"Circle claim state: {item.claim_circle_state or '-'}"
            )
            self.stdout.write(
                f"Arc claim transaction: {item.claim_arc_transaction_hash or '-'}"
            )
            self.stdout.write(
                f"Claim failure stage: {item.claim_failure_stage or '-'}"
            )
            self.stdout.write(
                f"Claim failure: {item.claim_failure_message or '-'}"
            )
            self.stdout.write(f"Claim started: {item.claim_started_at or '-'}")
            self.stdout.write(f"Claim confirmed: {item.claim_confirmed_at or '-'}")
            self.stdout.write(f"Execution attempts: {item.execution_attempt_count}")
            self.stdout.write(f"Execution branch: {item.execution_branch_name or '-'}")
            self.stdout.write(f"Execution workspace: {item.execution_workspace_name or '-'}")
            self.stdout.write(f"Baseline tests passed: {item.execution_baseline_test_passed}")
            self.stdout.write(f"Post-change tests passed: {item.execution_post_test_passed}")
            self.stdout.write(f"Execution changed files: {len(item.execution_changed_files or [])}")
            self.stdout.write(f"Execution commit: {item.execution_commit_sha or '-'}")
            self.stdout.write(f"Execution pull request: {item.execution_pull_request_url or '-'}")
            self.stdout.write(f"Execution failure stage: {item.execution_failure_stage or '-'}")
            self.stdout.write(f"Execution failure: {item.execution_failure_message or '-'}")
            self.stdout.write(f"Execution started: {item.execution_started_at or '-'}")
            self.stdout.write(f"Execution completed: {item.execution_completed_at or '-'}")
            self.stdout.write(f"Submission attempts: {item.submission_attempt_count}")
            self.stdout.write(f"Submission commit hash: {item.submission_commit_hash or '-'}")
            self.stdout.write(f"Submission deliverable hash: {item.submission_deliverable_hash or '-'}")
            self.stdout.write(f"Circle submission transaction: {item.submission_circle_transaction_id or '-'}")
            self.stdout.write(f"Circle submission state: {item.submission_circle_state or '-'}")
            self.stdout.write(f"Arc submission transaction: {item.submission_arc_transaction_hash or '-'}")
            self.stdout.write(f"Submission failure stage: {item.submission_failure_stage or '-'}")
            self.stdout.write(f"Submission failure: {item.submission_failure_message or '-'}")
            self.stdout.write(f"Submission confirmed: {item.submission_confirmed_at or '-'}")

        self.stdout.write("")
        self.stdout.write("Secrets displayed: none")
