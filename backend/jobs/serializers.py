from django.conf import settings
from django.utils import timezone
from rest_framework import serializers
from jobs.models import JobDraft, Notification, VeyraJob


class GithubIssuePreviewSerializer(serializers.Serializer):
    github_issue_url = serializers.URLField()


class JobDraftSerializer(serializers.ModelSerializer):
    github_repository = serializers.SerializerMethodField()

    class Meta:
        model = JobDraft
        fields = [
            'id', 'status', 'github_issue_url', 'github_repository_access', 'github_repository',
            'repository_owner', 'repository_name', 'target_branch', 'issue_number',
            'issue_title', 'issue_body', 'budget_usdc', 'deadline',
            'acceptance_criteria', 'advanced_options', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'status', 'github_repository_access', 'github_repository',
            'repository_owner', 'repository_name', 'target_branch', 'issue_number',
            'issue_title', 'issue_body', 'created_at', 'updated_at',
        ]

    def get_github_repository(self, obj):
        access = getattr(obj, 'github_repository_access', None)
        if not access:
            return None
        return {
            'id': str(access.id),
            'full_name': access.full_name,
            'private': access.private,
            'default_branch': access.default_branch,
            'active': access.active,
            'installation_status': access.installation.status,
        }

    def validate_advanced_options(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Advanced options must be an object.')
        if (
            'require_github_checks' in value
            and not isinstance(value.get('require_github_checks'), bool)
        ):
            raise serializers.ValidationError(
                'require_github_checks must be true or false.'
            )
        return value

    def validate_acceptance_criteria(self, value):
        if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
            raise serializers.ValidationError('Acceptance criteria must be a list of clear statements.')
        if not value:
            raise serializers.ValidationError('Add at least one acceptance criterion.')
        return [item.strip() for item in value]

    def validate_budget_usdc(self, value):
        if value <= 0:
            raise serializers.ValidationError('Budget must be greater than zero.')
        return value

    def validate_deadline(self, value):
        seconds = (value - timezone.now()).total_seconds()
        minimum_seconds = max(
            600,
            int(getattr(settings, 'WORKER_DISCOVERY_MIN_REMAINING_SECONDS', 900)),
        )
        if seconds < minimum_seconds:
            minimum_minutes = (minimum_seconds + 59) // 60
            raise serializers.ValidationError(
                f'Deadline must be at least {minimum_minutes} minutes from now '
                'so automatic matching has enough time.'
            )
        if seconds > 90 * 24 * 60 * 60:
            raise serializers.ValidationError('Deadline cannot exceed 90 days.')
        return value


class JobSummarySerializer(serializers.ModelSerializer):
    title = serializers.SerializerMethodField()
    github_issue_url = serializers.URLField(source='draft.github_issue_url')
    budget_usdc = serializers.SerializerMethodField()

    class Meta:
        model = VeyraJob
        fields = ['onchain_job_id', 'title', 'github_issue_url', 'client_status', 'status', 'budget_usdc', 'provider_address', 'expires_at', 'updated_at']

    def get_title(self, obj) -> str:
        return (obj.draft.advanced_options or {}).get('job_title') or obj.draft.issue_title

    def get_budget_usdc(self, obj) -> str:
        return str(obj.draft.budget_usdc)


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'event_type', 'title', 'body', 'resource_type', 'resource_id', 'read_at', 'created_at']
