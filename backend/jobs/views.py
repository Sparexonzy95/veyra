from django.conf import settings
from drf_spectacular.utils import OpenApiTypes, extend_schema
from django.db.models import Count
from django.shortcuts import get_object_or_404
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from common.permissions import HasClientCapability
from jobs.github import fetch_issue, parse_issue_url
from jobs.github_app import repository_access_for_url, token_for_repository
from jobs.models import JobDraft, Notification, VeyraJob
from jobs.serializers import GithubIssuePreviewSerializer, JobDraftSerializer, JobSummarySerializer, NotificationSerializer
from jobs.services import create_approval_challenge, create_contextual_action_challenge, create_job_challenge, ensure_required_github_ci_ready, refresh_job_projection
from blockchain.services import available_client_action
from wallets.models import CircleTransaction, WalletAccount
from wallets.services import extract_circle_user_token
from workers.execution_status import job_execution_snapshot
from workers.execution_recovery import RuntimeRetryRefused, retry_existing_runtime_assignment
from workers.models import WorkerJobAssignment
from wallets.transaction_sync import (
    attach_circle_transaction, mark_challenge_completed, sync_transaction,
    transaction_payload,
)

class GithubIssuePreviewView(APIView):
    permission_classes = [HasClientCapability]

    @extend_schema(request=GithubIssuePreviewSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        serializer = GithubIssuePreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        url = serializer.validated_data['github_issue_url']
        parsed = parse_issue_url(url)
        access = repository_access_for_url(
            client=request.user,
            owner=parsed['owner'],
            repository=parsed['repo'],
        )
        token = token_for_repository(access)
        payload = fetch_issue(url, token=token.token)
        payload['github_repository_access_id'] = str(access.id)
        payload['github_installation_status'] = access.installation.status
        return Response(payload)

class JobDraftViewSet(viewsets.ModelViewSet):
    queryset = JobDraft.objects.all()
    permission_classes = [HasClientCapability]
    serializer_class = JobDraftSerializer

    def get_queryset(self):
        return JobDraft.objects.select_related(
            'github_repository_access__installation'
        ).filter(client=self.request.user).exclude(status=JobDraft.Status.ARCHIVED)

    def perform_create(self, serializer):
        url = serializer.validated_data['github_issue_url']
        parsed = parse_issue_url(url)
        access = repository_access_for_url(
            client=self.request.user,
            owner=parsed['owner'],
            repository=parsed['repo'],
        )
        issue = fetch_issue(url, token=token_for_repository(access).token)
        criteria = serializer.validated_data.get('acceptance_criteria') or issue['acceptance_criteria']
        if not criteria:
            raise ValidationError('Add at least one acceptance criterion.')
        serializer.save(
            client=self.request.user,
            github_repository_access=access,
            acceptance_criteria=criteria,
            **{k: issue[k] for k in [
                'repository_owner', 'repository_name', 'target_branch', 'issue_number', 'issue_title', 'issue_body'
            ]},
        )

    def perform_update(self, serializer):
        if serializer.instance.status not in [JobDraft.Status.DRAFT, JobDraft.Status.READY]:
            raise ValidationError('A locked or funded job cannot be edited.')
        url = serializer.validated_data.get(
            'github_issue_url', serializer.instance.github_issue_url
        )
        parsed = parse_issue_url(url)
        access = repository_access_for_url(
            client=self.request.user,
            owner=parsed['owner'],
            repository=parsed['repo'],
        )
        issue = fetch_issue(url, token=token_for_repository(access).token)
        criteria = serializer.validated_data.get(
            'acceptance_criteria', serializer.instance.acceptance_criteria
        ) or issue['acceptance_criteria']
        if not criteria:
            raise ValidationError('Add at least one acceptance criterion.')
        serializer.save(
            github_repository_access=access,
            acceptance_criteria=criteria,
            **{k: issue[k] for k in [
                'repository_owner', 'repository_name', 'target_branch',
                'issue_number', 'issue_title', 'issue_body',
            ]},
        )

    def perform_destroy(self, instance):
        if instance.status not in [JobDraft.Status.DRAFT, JobDraft.Status.READY]:
            raise ValidationError('A locked or funded job cannot be deleted.')
        instance.status = JobDraft.Status.ARCHIVED
        instance.save(update_fields=['status', 'updated_at'])


    def _assert_repository_ready(self, draft):
        access = getattr(draft, 'github_repository_access', None)
        if not access:
            raise ValidationError(
                'Connect this repository through the Veyra GitHub App before continuing.'
            )
        repository_access_for_url(
            client=self.request.user,
            owner=draft.repository_owner,
            repository=draft.repository_name,
        )


    @action(detail=True, methods=['post'])
    def review(self, request, pk=None):
        draft = self.get_object()
        if draft.status not in [JobDraft.Status.DRAFT, JobDraft.Status.READY]:
            raise ValidationError('This job is already locked for funding.')
        self._assert_repository_ready(draft)
        ci_preflight = ensure_required_github_ci_ready(draft)
        draft.status = JobDraft.Status.READY
        draft.save(update_fields=['status', 'updated_at'])
        return Response({
            'draft_id': draft.id,
            'title': (draft.advanced_options or {}).get('job_title') or draft.issue_title,
            'repository': f'{draft.repository_owner}/{draft.repository_name}',
            'budget_usdc': str(draft.budget_usdc),
            'deadline': draft.deadline,
            'acceptance_criteria': draft.acceptance_criteria,
            'payment_protection': 'Funds remain locked until work passes verification.',
            'verification_requirements': {
                'veyra_independent_verification': True,
                'funded_validation': True,
                'github_ci_required': bool((draft.advanced_options or {}).get('require_github_checks', False)),
                'github_ci_preflight': ci_preflight,
            },
        })

    @action(detail=True, methods=['post'], url_path='approval-challenge')
    def approval_challenge(self, request, pk=None):
        draft = self.get_object()
        self._assert_repository_ready(draft)
        return Response(create_approval_challenge(draft, extract_circle_user_token(request)))

    @action(detail=True, methods=['post'], url_path='funding-challenge')
    def funding_challenge(self, request, pk=None):
        draft = self.get_object()
        self._assert_repository_ready(draft)
        return Response(create_job_challenge(draft, extract_circle_user_token(request)))

class ClientJobViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = VeyraJob.objects.select_related('draft', 'worker_assignment__worker', 'worker_assignment__queue_item').all()
    permission_classes = [HasClientCapability]
    serializer_class = JobSummarySerializer
    lookup_field = 'onchain_job_id'

    def get_queryset(self):
        return VeyraJob.objects.select_related('draft', 'worker_assignment__worker', 'worker_assignment__queue_item').filter(client=self.request.user)

    def retrieve(self, request, *args, **kwargs):
        job = self.get_object()
        try:
            onchain = refresh_job_projection(job)
        except Exception:
            onchain = None
        data = JobSummarySerializer(job).data
        data.update({
            'acceptance_criteria': job.draft.acceptance_criteria,
            'repository': f'{job.draft.repository_owner}/{job.draft.repository_name}',
            'issue_number': job.draft.issue_number,
            'pull_request_number': job.pull_request_number,
            'commit_hash': job.commit_hash,
            'report_hash': job.report_hash,
            'evidence_hash': job.evidence_hash,
            'onchain': onchain,
            'available_action': available_client_action(onchain) if onchain else None,
            'execution': job_execution_snapshot(job),
            'verification_requirements': {
                'veyra_independent_verification': True,
                'funded_validation': True,
                'github_ci_required': bool(
                    (getattr(job.draft, 'funding_snapshot', None) and
                     (job.draft.funding_snapshot.policy_commitment or {}).get('requireGithubChecks', False))
                ),
            },
        })
        return Response(data)

    @action(detail=True, methods=['post'], url_path='action-challenge')
    def action_challenge(self, request, onchain_job_id=None):
        return Response(create_contextual_action_challenge(self.get_object(), extract_circle_user_token(request)))

    @action(detail=True, methods=['post'], url_path='retry-execution')
    def retry_execution(self, request, onchain_job_id=None):
        job = self.get_object()
        try:
            assignment = job.worker_assignment
        except WorkerJobAssignment.DoesNotExist:
            return Response(
                {
                    'error': {
                        'code': 'ASSIGNMENT_NOT_FOUND',
                        'message': 'This job has no existing assignment to retry.',
                    },
                },
                status=status.HTTP_409_CONFLICT,
            )
        try:
            assignment, changed = retry_existing_runtime_assignment(assignment)
        except RuntimeRetryRefused as exc:
            return Response(
                {'error': {'code': exc.code, 'message': str(exc)}},
                status=status.HTTP_409_CONFLICT,
            )
        return Response({
            'code': 'EXECUTION_RETRY_SCHEDULED' if changed else 'EXECUTION_RETRY_ALREADY_SCHEDULED',
            'message': (
                'The failed execution step was queued again on the existing funded job.'
                if changed else
                'This execution retry is already queued on the existing funded job.'
            ),
            'job_id': int(job.onchain_job_id),
            'assignment_id': str(assignment.id),
            'assignment_attempt': int(assignment.assignment_attempt),
            'claim_preserved': True,
        })

class DashboardView(APIView):
    permission_classes = [HasClientCapability]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        wallet = request.user.wallet_accounts.filter(
            blockchain=settings.ARC_BLOCKCHAIN,
            purpose=WalletAccount.Purpose.CLIENT_ESCROW,
        ).first()
        jobs = VeyraJob.objects.select_related('draft').filter(client=request.user)
        counts = {item['client_status']: item['count'] for item in jobs.values('client_status').annotate(count=Count('id'))}
        return Response({
            'wallet': {
                'address': wallet.address,
                'blockchain': wallet.blockchain,
                'usdc_balance': str(wallet.last_usdc_balance),
            } if wallet else None,
            'job_counts': counts,
            'jobs': JobSummarySerializer(jobs[:10], many=True).data,
            'notifications': NotificationSerializer(request.user.notifications.all()[:10], many=True).data,
        })

class CircleTransactionListView(APIView):
    permission_classes = [HasClientCapability]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        queryset = CircleTransaction.objects.select_related('draft', 'job').filter(user=request.user)
        draft_id = request.query_params.get('draft_id')
        if draft_id:
            queryset = queryset.filter(draft_id=draft_id)
        purpose = request.query_params.get('purpose')
        if purpose:
            queryset = queryset.filter(purpose=purpose)
        return Response({'results': [transaction_payload(tx) for tx in queryset[:50]]})


class CircleTransactionStatusView(APIView):
    permission_classes = [HasClientCapability]

    def _get_transaction(self, request, transaction_id):
        return get_object_or_404(
            CircleTransaction.objects.select_related('draft', 'job'),
            id=transaction_id,
            user=request.user,
        )

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, transaction_id):
        tx = self._get_transaction(request, transaction_id)
        user_token = request.headers.get('X-Circle-User-Token', '')
        tx = sync_transaction(tx, user_token=user_token or None)
        return Response(transaction_payload(tx))

    @extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
    def post(self, request, transaction_id):
        tx = self._get_transaction(request, transaction_id)
        user_token = extract_circle_user_token(request)

        # User-controlled contractExecution returns only challengeId when the
        # challenge is created. After the user approves in the Circle SDK, mark
        # the local record complete and resolve the Circle transaction by the
        # exact refId Veyra supplied during challenge creation.
        browser_transaction_id = str(
            request.data.get('circle_transaction_id') or ''
        ).strip()

        tx = mark_challenge_completed(tx)
        if browser_transaction_id:
            tx = attach_circle_transaction(
                tx,
                circle_transaction_id=browser_transaction_id,
                user_token=user_token,
            )

        tx = sync_transaction(tx, user_token=user_token, force=True)
        return Response(transaction_payload(tx))
