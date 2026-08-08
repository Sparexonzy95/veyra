from datetime import timedelta
from unittest.mock import patch
from types import SimpleNamespace
from django.conf import settings
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from accounts.models import User, UserCapability
from accounts.services import grant_client, issue_session
from jobs.models import GitHubAppInstallation, GitHubRepositoryAccess, JobDraft
from jobs.services import commitment_hash, lock_funding_snapshot
from wallets.models import WalletAccount

class CommitmentTests(TestCase):
    def test_canonical_commitment_is_deterministic(self):
        self.assertEqual(commitment_hash({'b': 2, 'a': 1}), commitment_hash({'a': 1, 'b': 2}))

    def test_snapshot_locks_deployed_contract_inputs(self):
        user = User.objects.create_user()
        draft = JobDraft.objects.create(
            client=user,
            github_issue_url='https://github.com/o/r/issues/1',
            repository_owner='o', repository_name='r', issue_number=1,
            issue_title='Fix bug', issue_body='Details', budget_usdc='10.000000',
            deadline=timezone.now() + timedelta(days=1),
            acceptance_criteria=['Tests pass'],
        )
        snapshot = lock_funding_snapshot(draft)
        self.assertEqual(int(snapshot.budget_atomic), 10_000_000)
        self.assertTrue(snapshot.repository_hash.startswith('0x'))
        self.assertEqual(snapshot.verifier_address, settings.VEYRA_VERIFIER_ADDRESS.lower())
        self.assertFalse(snapshot.policy_commitment['requireGithubChecks'])

    def test_snapshot_commits_explicit_github_ci_requirement(self):
        user = User.objects.create_user()
        draft = JobDraft.objects.create(
            client=user,
            github_issue_url='https://github.com/o/r/issues/2',
            repository_owner='o', repository_name='r', issue_number=2,
            issue_title='Fix CI bug', issue_body='Details', budget_usdc='10.000000',
            deadline=timezone.now() + timedelta(days=1),
            acceptance_criteria=['Tests pass'],
            advanced_options={'require_github_checks': True},
        )

        snapshot = lock_funding_snapshot(draft)

        self.assertTrue(snapshot.policy_commitment['requireGithubChecks'])

class JobDraftApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(display_name='Client')
        grant_client(self.user)
        WalletAccount.objects.create(
            user=self.user, circle_wallet_id='wallet-1',
            address='0x1111111111111111111111111111111111111111', blockchain='ARC-TESTNET',
        )
        raw, _ = issue_session(self.user, type('Request', (), {'headers': {}})())
        self.client = APIClient()
        self.client.cookies[settings.VEYRA_SESSION_COOKIE] = raw
        self.client.credentials(HTTP_ORIGIN='http://localhost:3000')
        self.github_installation = GitHubAppInstallation.objects.create(
            client=self.user,
            installation_id=1001,
            account_id=77,
            account_login='o',
            account_type='User',
            permissions={
                'contents': 'write',
                'issues': 'read',
                'pull_requests': 'write',
                'checks': 'read',
            },
            status=GitHubAppInstallation.Status.CONNECTED,
        )
        self.github_repository = GitHubRepositoryAccess.objects.create(
            installation=self.github_installation,
            github_repository_id=2001,
            owner='o',
            name='r',
            full_name='o/r',
            default_branch='main',
            active=True,
        )
        token_patch = patch(
            'jobs.views.token_for_repository',
            return_value=SimpleNamespace(token='installation-token'),
        )
        token_patch.start()
        self.addCleanup(token_patch.stop)

    @patch('jobs.views.fetch_issue')
    def test_create_simple_job_draft(self, fetch_issue):
        fetch_issue.return_value = {
            'github_issue_url': 'https://github.com/o/r/issues/1',
            'repository_owner': 'o', 'repository_name': 'r', 'target_branch': 'main',
            'issue_number': 1, 'issue_title': 'Fix bug', 'issue_body': 'Details',
            'acceptance_criteria': ['Tests pass'],
        }
        response = self.client.post('/api/v1/client/job-drafts/', {
            'github_issue_url': 'https://github.com/o/r/issues/1',
            'budget_usdc': '10.000000',
            'deadline': (timezone.now() + timedelta(days=1)).isoformat(),
            'acceptance_criteria': ['Tests pass'],
            'advanced_options': {},
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(JobDraft.objects.count(), 1)


    @patch('jobs.views.fetch_issue')
    @patch('jobs.services.github_ci_preflight')
    def test_review_blocks_required_github_ci_when_repository_is_not_ready(
        self, ci_preflight, fetch_issue
    ):
        fetch_issue.return_value = {
            'github_issue_url': 'https://github.com/o/r/issues/3',
            'repository_owner': 'o', 'repository_name': 'r', 'target_branch': 'main',
            'issue_number': 3, 'issue_title': 'CI required', 'issue_body': 'Details',
            'acceptance_criteria': ['Tests pass'],
        }
        ci_preflight.return_value = {
            'ready': False,
            'message': 'No GitHub CI configuration or existing Check Run provider was detected for this branch.',
        }
        create = self.client.post('/api/v1/client/job-drafts/', {
            'github_issue_url': 'https://github.com/o/r/issues/3',
            'budget_usdc': '10.000000',
            'deadline': (timezone.now() + timedelta(days=1)).isoformat(),
            'acceptance_criteria': ['Tests pass'],
            'advanced_options': {'require_github_checks': True},
        }, format='json')

        response = self.client.post(
            f"/api/v1/client/job-drafts/{create.data['id']}/review/", {}, format='json'
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('No GitHub CI', str(response.data))
        self.assertEqual(JobDraft.objects.get(id=create.data['id']).status, JobDraft.Status.DRAFT)

    @patch('jobs.views.fetch_issue')
    @patch('jobs.services.github_ci_preflight')
    def test_review_allows_required_github_ci_when_preflight_is_ready(
        self, ci_preflight, fetch_issue
    ):
        fetch_issue.return_value = {
            'github_issue_url': 'https://github.com/o/r/issues/4',
            'repository_owner': 'o', 'repository_name': 'r', 'target_branch': 'main',
            'issue_number': 4, 'issue_title': 'CI ready', 'issue_body': 'Details',
            'acceptance_criteria': ['Tests pass'],
        }
        ci_preflight.return_value = {
            'ready': True,
            'source': 'AUTOMATIC_WORKFLOW',
            'message': 'GitHub CI is ready.',
        }
        create = self.client.post('/api/v1/client/job-drafts/', {
            'github_issue_url': 'https://github.com/o/r/issues/4',
            'budget_usdc': '10.000000',
            'deadline': (timezone.now() + timedelta(days=1)).isoformat(),
            'acceptance_criteria': ['Tests pass'],
            'advanced_options': {'require_github_checks': True},
        }, format='json')

        response = self.client.post(
            f"/api/v1/client/job-drafts/{create.data['id']}/review/", {}, format='json'
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['verification_requirements']['github_ci_required'])
        self.assertTrue(response.data['verification_requirements']['github_ci_preflight']['ready'])
        self.assertEqual(JobDraft.objects.get(id=create.data['id']).status, JobDraft.Status.READY)

    @patch('jobs.views.fetch_issue')
    @patch('jobs.services.github_ci_preflight')
    def test_required_github_ci_is_rechecked_before_wallet_funding_lock(
        self, ci_preflight, fetch_issue
    ):
        fetch_issue.return_value = {
            'github_issue_url': 'https://github.com/o/r/issues/5',
            'repository_owner': 'o', 'repository_name': 'r', 'target_branch': 'main',
            'issue_number': 5, 'issue_title': 'CI changes', 'issue_body': 'Details',
            'acceptance_criteria': ['Tests pass'],
        }
        ci_preflight.side_effect = [
            {'ready': True, 'source': 'AUTOMATIC_WORKFLOW', 'message': 'GitHub CI is ready.'},
            {'ready': False, 'source': 'NO_CI_EVIDENCE', 'message': 'GitHub CI is no longer ready.'},
        ]
        create = self.client.post('/api/v1/client/job-drafts/', {
            'github_issue_url': 'https://github.com/o/r/issues/5',
            'budget_usdc': '10.000000',
            'deadline': (timezone.now() + timedelta(days=1)).isoformat(),
            'acceptance_criteria': ['Tests pass'],
            'advanced_options': {'require_github_checks': True},
        }, format='json')
        draft_id = create.data['id']
        review = self.client.post(
            f'/api/v1/client/job-drafts/{draft_id}/review/', {}, format='json'
        )
        self.assertEqual(review.status_code, 200, review.data)

        approval = self.client.post(
            f'/api/v1/client/job-drafts/{draft_id}/approval-challenge/',
            {},
            format='json',
            HTTP_X_CIRCLE_USER_TOKEN='u' * 40,
        )

        self.assertEqual(approval.status_code, 400, approval.data)
        self.assertIn('no longer ready', str(approval.data).lower())
        draft = JobDraft.objects.get(id=draft_id)
        self.assertEqual(draft.status, JobDraft.Status.READY)
        self.assertFalse(hasattr(draft, 'funding_snapshot'))

from unittest.mock import MagicMock
from django.test import override_settings

@override_settings(CIRCLE_API_KEY='test-key')
class ClientFundingApiFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(display_name='Client')
        grant_client(self.user)
        self.wallet = WalletAccount.objects.create(
            user=self.user, circle_wallet_id='wallet-flow',
            address='0x1111111111111111111111111111111111111111', blockchain='ARC-TESTNET',
        )
        raw, _ = issue_session(self.user, type('Request', (), {'headers': {}})())
        self.client = APIClient()
        self.client.cookies[settings.VEYRA_SESSION_COOKIE] = raw
        self.client.credentials(HTTP_ORIGIN='http://localhost:3000')
        self.github_installation = GitHubAppInstallation.objects.create(
            client=self.user,
            installation_id=1001,
            account_id=77,
            account_login='o',
            account_type='User',
            permissions={
                'contents': 'write',
                'issues': 'read',
                'pull_requests': 'write',
                'checks': 'read',
            },
            status=GitHubAppInstallation.Status.CONNECTED,
        )
        self.github_repository = GitHubRepositoryAccess.objects.create(
            installation=self.github_installation,
            github_repository_id=2001,
            owner='o',
            name='r',
            full_name='o/r',
            default_branch='main',
            active=True,
        )
        token_patch = patch(
            'jobs.views.token_for_repository',
            return_value=SimpleNamespace(token='installation-token'),
        )
        token_patch.start()
        self.addCleanup(token_patch.stop)
        self.circle_user_token = 'u' * 40

    @patch('jobs.views.fetch_issue')
    def test_review_approval_and_funding_challenges(self, fetch_issue):
        fetch_issue.return_value = {
            'github_issue_url': 'https://github.com/o/r/issues/1',
            'repository_owner': 'o', 'repository_name': 'r', 'target_branch': 'main',
            'issue_number': 1, 'issue_title': 'Fix bug', 'issue_body': 'Details',
            'acceptance_criteria': ['Tests pass'],
        }
        create = self.client.post('/api/v1/client/job-drafts/', {
            'github_issue_url': 'https://github.com/o/r/issues/1',
            'budget_usdc': '10.000000',
            'deadline': (timezone.now() + timedelta(days=1)).isoformat(),
            'acceptance_criteria': ['Tests pass'],
            'advanced_options': {},
        }, format='json')
        draft_id = create.data['id']

        review = self.client.post(f'/api/v1/client/job-drafts/{draft_id}/review/', {}, format='json')
        self.assertEqual(review.status_code, 200)
        self.assertEqual(JobDraft.objects.get(id=draft_id).status, 'READY')

        arc = MagicMock()
        arc.allowance.side_effect = [0, 10_000_000]
        arc.encode_approve.return_value = '0x095ea7b3' + '00' * 64
        arc.is_paused.return_value = False
        arc.is_verifier_authorised.return_value = True
        arc.encode_create_job.return_value = '0xbb0a450e' + '00' * 224
        circle = MagicMock()
        circle.create_contract_execution.side_effect = [
            {'challengeId': 'approve-challenge'},
            {'challengeId': 'fund-challenge'},
        ]

        with patch('jobs.services.verify_circle_session_for_user', return_value=(circle, self.wallet)), \
             patch('jobs.services.ArcClient', return_value=arc), \
             patch('jobs.services.CircleClient', return_value=circle):
            approval = self.client.post(
                f'/api/v1/client/job-drafts/{draft_id}/approval-challenge/', {}, format='json',
                HTTP_X_CIRCLE_USER_TOKEN=self.circle_user_token,
            )
            self.assertEqual(approval.status_code, 200, approval.data)
            self.assertTrue(approval.data['approval_required'])

            funding = self.client.post(
                f'/api/v1/client/job-drafts/{draft_id}/funding-challenge/', {}, format='json',
                HTTP_X_CIRCLE_USER_TOKEN=self.circle_user_token,
            )
            self.assertEqual(funding.status_code, 200, funding.data)
            self.assertEqual(funding.data['challenge_id'], 'fund-challenge')
            self.assertEqual(JobDraft.objects.get(id=draft_id).status, 'FUNDING')

    def test_existing_draft_remains_usable_when_allowance_is_one_usdc(self):
        draft = JobDraft.objects.create(
            client=self.user,
            github_repository_access=self.github_repository,
            github_issue_url='https://github.com/o/r/issues/2',
            repository_owner='o',
            repository_name='r',
            target_branch='main',
            issue_number=2,
            issue_title='Existing draft',
            issue_body='Keep this draft usable',
            budget_usdc='1.000000',
            deadline=timezone.now() + timedelta(days=1),
            acceptance_criteria=['Tests pass'],
            status=JobDraft.Status.READY,
        )
        arc = MagicMock()
        arc.allowance.return_value = 1_000_000
        circle = MagicMock()

        with patch(
            'jobs.services.verify_circle_session_for_user',
            return_value=(circle, self.wallet),
        ), patch('jobs.services.ArcClient', return_value=arc):
            approval = self.client.post(
                f'/api/v1/client/job-drafts/{draft.id}/approval-challenge/',
                {},
                format='json',
                HTTP_X_CIRCLE_USER_TOKEN=self.circle_user_token,
            )

        self.assertEqual(approval.status_code, 200, approval.data)
        self.assertEqual(
            approval.data,
            {'approval_required': False, 'allowance_atomic': 1_000_000},
        )
        arc.encode_approve.assert_not_called()
        circle.create_contract_execution.assert_not_called()
        draft.refresh_from_db()
        self.assertEqual(draft.status, JobDraft.Status.LOCKED)
        self.assertEqual(str(draft.budget_usdc), '1.000000')
        self.assertEqual(
            self.client.get(f'/api/v1/client/job-drafts/{draft.id}/').status_code,
            200,
        )
