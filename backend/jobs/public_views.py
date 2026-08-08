"""Public, unauthenticated read-only endpoints for browsing open Veyra work.

These are the only job endpoints that do not require a Veyra session. They are
intentionally read-only and return a narrow projection built by the public
serializers. The queryset is constrained so only genuinely browseable work is
ever visible:

- status == FUNDED       (escrow is locked and the job exists on-chain)
- client_status == OPEN  (accepting work; not claimed, completed, cancelled,
                          rejected, abandoned, expired or refunded)

Draft and locked JobDrafts never appear here because only funded jobs are
projected into VeyraJob. Private client-only records, verification secrets and
repository credentials are never included.
"""

from decimal import Decimal, InvalidOperation

from django.db.models import Q
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny

from jobs.models import VeyraJob
from jobs.public_serializers import (
    PublicIssueDetailSerializer,
    PublicIssueSerializer,
    issue_labels,
    stack_names,
    task_type_label,
)

# The single definition of "publicly browseable". Reused by the queryset and
# by the filter-facet endpoint so they can never drift apart.
PUBLIC_OPEN_FILTER = Q(status='FUNDED', client_status='OPEN')

ZERO_ADDRESS = '0x0000000000000000000000000000000000000000'


def is_public(job: VeyraJob) -> bool:
    """A job invited to a specific agent is private, not browseable."""
    invited = (job.draft.advanced_options or {}).get('invited_provider_address')
    return not invited or str(invited).lower() == ZERO_ADDRESS


def public_open_jobs():
    return (
        VeyraJob.objects.select_related('draft', 'client__client_profile')
        .filter(PUBLIC_OPEN_FILTER, invited_provider_address__iexact=ZERO_ADDRESS)
    )


class PublicIssuePagination(PageNumberPagination):
    page_size = 6
    page_size_query_param = None
    max_page_size = 6


class PublicIssueViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    pagination_class = PublicIssuePagination
    lookup_field = 'onchain_job_id'
    lookup_url_kwarg = 'reference'

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return PublicIssueDetailSerializer
        return PublicIssueSerializer

    def get_object(self):
        from django.shortcuts import get_object_or_404

        reference = self.kwargs[self.lookup_url_kwarg]
        job = get_object_or_404(public_open_jobs(), onchain_job_id=reference)
        if not is_public(job):
            from django.http import Http404

            raise Http404('Issue is not publicly available.')
        return job

    def get_queryset(self):
        queryset = public_open_jobs()
        params = self.request.query_params

        search = (params.get('search') or '').strip()
        if search:
            queryset = queryset.filter(
                Q(draft__issue_title__icontains=search)
                | Q(draft__repository_name__icontains=search)
                | Q(draft__repository_owner__icontains=search)
                | Q(draft__issue_body__icontains=search)
            )

        project = (params.get('project') or '').strip()
        if project:
            queryset = queryset.filter(
                Q(draft__repository_name=project)
                | Q(draft__repository_owner=project)
            )

        min_reward = (params.get('min_reward') or '').strip()
        max_reward = (params.get('max_reward') or '').strip()
        try:
            if min_reward:
                queryset = queryset.filter(draft__budget_usdc__gte=Decimal(min_reward))
            if max_reward:
                queryset = queryset.filter(draft__budget_usdc__lte=Decimal(max_reward))
        except InvalidOperation:
            # Invalid public query values simply produce an unbounded range.
            pass

        # Facet filters that live inside advanced_options (JSON) are applied in
        # Python so we match the same normalisation the serializer exposes.
        rows = list(queryset.order_by('-created_at'))

        task_type = (params.get('task_type') or '').strip()
        label = (params.get('label') or '').strip()
        stack = (params.get('tech_stack') or '').strip()
        verification = (params.get('verification') or '').strip()
        sort = (params.get('sort') or 'newest').strip().lower()

        def matches(job: VeyraJob) -> bool:
            advanced = job.draft.advanced_options or {}
            if task_type and task_type_label(advanced) != task_type:
                return False
            if label and label not in issue_labels(advanced):
                return False
            if stack and stack not in stack_names(advanced):
                return False
            return True

        rows = [job for job in rows if matches(job)]

        if verification:
            from jobs.public_serializers import verification_method_label

            rows = [
                job
                for job in rows
                if verification_method_label(job.draft.advanced_options or {})
                == verification
            ]

        def reward_of(job: VeyraJob) -> Decimal:
            try:
                return Decimal(str(job.draft.budget_usdc))
            except (InvalidOperation, TypeError, ValueError):
                return Decimal(0)

        if sort == 'oldest':
            rows.sort(key=lambda job: job.created_at)
        elif sort in ('reward', 'reward_desc', 'reward-high'):
            rows.sort(key=reward_of, reverse=True)
        elif sort in ('deadline', 'deadline_soon', 'deadline-soonest'):
            rows.sort(key=lambda job: job.draft.deadline)
        else:  # newest (default)
            rows.sort(key=lambda job: job.created_at, reverse=True)
        return rows


class PublicIssueFacetsView(viewsets.ViewSet):
    """Distinct, API-derived filter values for the Explore sidebar."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def list(self, request):
        from rest_framework.response import Response

        from jobs.public_serializers import verification_method_label

        jobs = list(public_open_jobs())
        projects: set[str] = set()
        task_types: set[str] = set()
        labels: set[str] = set()
        stacks: set[str] = set()
        verifications: set[str] = set()
        rewards: list[float] = []

        for job in jobs:
            advanced = job.draft.advanced_options or {}
            projects.add(job.draft.repository_name)
            task_types.add(task_type_label(advanced))
            labels.update(issue_labels(advanced))
            stacks.update(stack_names(advanced))
            verifications.add(verification_method_label(advanced))
            try:
                rewards.append(float(job.draft.budget_usdc))
            except (TypeError, ValueError):
                pass

        return Response(
            {
                'total_open': len(jobs),
                'projects': sorted(projects),
                'task_types': sorted(task_types),
                'labels': sorted(labels),
                'tech_stacks': sorted(stacks),
                'verification_methods': sorted(verifications),
                'reward_range': {
                    'min': min(rewards) if rewards else 0,
                    'max': max(rewards) if rewards else 0,
                },
            }
        )
