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
from jobs.github import fetch_issue
from jobs.models import JobDraft, Notification, VeyraJob
from jobs.serializers import GithubIssuePreviewSerializer, JobDraftSerializer, JobSummarySerializer, NotificationSerializer
from jobs.services import create_approval_challenge, create_contextual_action_challenge, create_job_challenge, refresh_job_projection
from blockchain.services import available_client_action
from wallets.models import CircleTransaction
from wallets.services import extract_circle_user_token
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
        return Response(fetch_issue(serializer.validated_data['github_issue_url']))

class JobDraftViewSet(viewsets.ModelViewSet):
    queryset = JobDraft.objects.all()
    permission_classes = [HasClientCapability]
    serializer_class = JobDraftSerializer

    def get_queryset(self):
        return JobDraft.objects.filter(client=self.request.user).exclude(status=JobDraft.Status.ARCHIVED)

    def perform_create(self, serializer):
        issue = fetch_issue(serializer.validated_data['github_issue_url'])
        criteria = serializer.validated_data.get('acceptance_criteria') or issue['acceptance_criteria']
        if not criteria:
            raise ValidationError('Add at least one acceptance criterion.')
        serializer.save(client=self.request.user, acceptance_criteria=criteria, **{k: issue[k] for k in [
            'repository_owner', 'repository_name', 'target_branch', 'issue_number', 'issue_title', 'issue_body'
        ]})

    def perform_update(self, serializer):
        if serializer.instance.status not in [JobDraft.Status.DRAFT, JobDraft.Status.READY]:
            raise ValidationError('A locked or funded job cannot be edited.')
        serializer.save()

    def perform_destroy(self, instance):
        if instance.status not in [JobDraft.Status.DRAFT, JobDraft.Status.READY]:
            raise ValidationError('A locked or funded job cannot be deleted.')
        instance.status = JobDraft.Status.ARCHIVED
        instance.save(update_fields=['status', 'updated_at'])

    @action(detail=True, methods=['post'])
    def review(self, request, pk=None):
        draft = self.get_object()
        if draft.status not in [JobDraft.Status.DRAFT, JobDraft.Status.READY]:
            raise ValidationError('This job is already locked for funding.')
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
        })

    @action(detail=True, methods=['post'], url_path='approval-challenge')
    def approval_challenge(self, request, pk=None):
        return Response(create_approval_challenge(self.get_object(), extract_circle_user_token(request)))

    @action(detail=True, methods=['post'], url_path='funding-challenge')
    def funding_challenge(self, request, pk=None):
        return Response(create_job_challenge(self.get_object(), extract_circle_user_token(request)))

class ClientJobViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = VeyraJob.objects.select_related('draft').all()
    permission_classes = [HasClientCapability]
    serializer_class = JobSummarySerializer
    lookup_field = 'onchain_job_id'

    def get_queryset(self):
        return VeyraJob.objects.select_related('draft').filter(client=self.request.user)

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
        })
        return Response(data)

    @action(detail=True, methods=['post'], url_path='action-challenge')
    def action_challenge(self, request, onchain_job_id=None):
        return Response(create_contextual_action_challenge(self.get_object(), extract_circle_user_token(request)))

class DashboardView(APIView):
    permission_classes = [HasClientCapability]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        wallet = request.user.wallet_accounts.filter(blockchain=settings.ARC_BLOCKCHAIN).first()
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
