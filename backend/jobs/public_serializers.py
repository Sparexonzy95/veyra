"""Public, read-only projection of open Veyra jobs.

Only funded jobs that are still open for work are ever exposed here, and only
fields that are safe for an anonymous visitor to read. Repository credentials,
commitment hashes, verifier addresses, allowed/forbidden paths, required
commands and any other internal verification configuration are deliberately
omitted.
"""

from rest_framework import serializers

from jobs.models import VeyraJob

# Human labels for the verification approach. The per-criterion method is a
# public statement of how work is judged; the underlying configuration
# (commands, paths, verifier address) is never surfaced.
_VERIFICATION_LABELS = {
    'TEST_SUITE': 'Automated test suite',
    'AUTOMATED_TEST': 'Automated test',
    'PULL_REQUEST_INSPECTION': 'Pull request inspection',
    'FILE_INSPECTION': 'File inspection',
    'MANUAL_REVIEW': 'Independent review',
}
_VERIFICATION_PRIORITY = (
    'TEST_SUITE',
    'AUTOMATED_TEST',
    'PULL_REQUEST_INSPECTION',
    'FILE_INSPECTION',
    'MANUAL_REVIEW',
)


def stack_names(advanced: dict) -> list[str]:
    names: list[str] = []
    for item in advanced.get('repository_stack') or []:
        if isinstance(item, dict):
            name = str(item.get('name') or '').strip()
            if name:
                names.append(name)
        elif isinstance(item, str) and item.strip():
            names.append(item.strip())
    return names


def issue_labels(advanced: dict) -> list[str]:
    labels: list[str] = []
    for label in advanced.get('labels') or []:
        if isinstance(label, str) and label.strip():
            labels.append(label.strip())
    return labels


def task_type_label(advanced: dict) -> str:
    raw = str(advanced.get('job_type') or 'FEATURE')
    return raw.replace('_', ' ').title()


def verification_method_label(advanced: dict) -> str:
    methods = advanced.get('criterion_verification_methods') or []
    for key in _VERIFICATION_PRIORITY:
        if key in methods:
            return _VERIFICATION_LABELS[key]
    return 'Independent verification'


def organisation_name(job: VeyraJob) -> str:
    profile = getattr(job.client, 'client_profile', None)
    if profile and (profile.organisation_name or '').strip():
        return profile.organisation_name.strip()
    return job.draft.repository_owner


class PublicIssueSerializer(serializers.Serializer):
    """Card-level fields for the public Explore Issues grid."""

    reference = serializers.IntegerField(source='onchain_job_id')
    organisation = serializers.SerializerMethodField()
    repository = serializers.SerializerMethodField()
    repository_name = serializers.CharField(source='draft.repository_name')
    title = serializers.SerializerMethodField()
    issue_number = serializers.IntegerField(source='draft.issue_number')
    task_type = serializers.SerializerMethodField()
    labels = serializers.SerializerMethodField()
    tech_stack = serializers.SerializerMethodField()
    reward_usdc = serializers.SerializerMethodField()
    deadline = serializers.DateTimeField(source='draft.deadline')
    verification_method = serializers.SerializerMethodField()
    published_at = serializers.DateTimeField(source='created_at')
    status = serializers.CharField(source='client_status')
    github_issue_url = serializers.URLField(source='draft.github_issue_url')

    def _advanced(self, job: VeyraJob) -> dict:
        return job.draft.advanced_options or {}

    def get_organisation(self, job: VeyraJob) -> str:
        return organisation_name(job)

    def get_repository(self, job: VeyraJob) -> str:
        return f'{job.draft.repository_owner}/{job.draft.repository_name}'

    def get_title(self, job: VeyraJob) -> str:
        return self._advanced(job).get('job_title') or job.draft.issue_title

    def get_task_type(self, job: VeyraJob) -> str:
        return task_type_label(self._advanced(job))

    def get_labels(self, job: VeyraJob) -> list[str]:
        return issue_labels(self._advanced(job))

    def get_tech_stack(self, job: VeyraJob) -> list[str]:
        return stack_names(self._advanced(job))

    def get_reward_usdc(self, job: VeyraJob) -> str:
        return str(job.draft.budget_usdc)

    def get_verification_method(self, job: VeyraJob) -> str:
        return verification_method_label(self._advanced(job))


class PublicIssueDetailSerializer(PublicIssueSerializer):
    """Adds the public task narrative for the issue-details route."""

    description = serializers.SerializerMethodField()
    acceptance_overview = serializers.SerializerMethodField()

    def get_description(self, job: VeyraJob) -> str:
        advanced = self._advanced(job)
        return advanced.get('job_description') or job.draft.issue_body or ''

    def get_acceptance_overview(self, job: VeyraJob) -> list[str]:
        # Only the plain acceptance statements are public. The per-criterion
        # verification configuration stored in the funding snapshot is not.
        criteria = job.draft.acceptance_criteria or []
        return [str(item).strip() for item in criteria if str(item).strip()]
