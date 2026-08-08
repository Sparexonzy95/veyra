from django.urls import include, path
from rest_framework.routers import DefaultRouter
from jobs.views import CircleTransactionListView, CircleTransactionStatusView, ClientJobViewSet, DashboardView, GithubIssuePreviewView, JobDraftViewSet
from jobs.github_views import GitHubConnectionStatusView, GitHubInstallStartView, GitHubInstallCompleteView, GitHubInstallationRefreshView, GitHubInstallationDisconnectView, GitHubRepositoryIssueListView, GitHubRepositoryCiPreflightView

router = DefaultRouter()
router.register('job-drafts', JobDraftViewSet, basename='job-draft')
router.register('jobs', ClientJobViewSet, basename='client-job')

urlpatterns = [
    path('dashboard/', DashboardView.as_view()),
    path('github/issue-preview/', GithubIssuePreviewView.as_view()),
    path('github/app/status/', GitHubConnectionStatusView.as_view()),
    path(
        'github/app/repositories/<uuid:repository_access_id>/issues/',
        GitHubRepositoryIssueListView.as_view(),
    ),
    path(
        'github/app/repositories/<uuid:repository_access_id>/ci-preflight/',
        GitHubRepositoryCiPreflightView.as_view(),
    ),
    path('github/app/install/start/', GitHubInstallStartView.as_view()),
    path('github/app/install/complete/', GitHubInstallCompleteView.as_view()),
    path('github/app/installations/<uuid:installation_id>/refresh/', GitHubInstallationRefreshView.as_view()),
    path('github/app/installations/<uuid:installation_id>/disconnect/', GitHubInstallationDisconnectView.as_view()),
    path('transactions/', CircleTransactionListView.as_view()),
    path('transactions/<uuid:transaction_id>/', CircleTransactionStatusView.as_view()),
    path('', include(router.urls)),
]
