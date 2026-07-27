from django.urls import include, path
from rest_framework.routers import DefaultRouter
from jobs.views import CircleTransactionListView, CircleTransactionStatusView, ClientJobViewSet, DashboardView, GithubIssuePreviewView, JobDraftViewSet

router = DefaultRouter()
router.register('job-drafts', JobDraftViewSet, basename='job-draft')
router.register('jobs', ClientJobViewSet, basename='client-job')

urlpatterns = [
    path('dashboard/', DashboardView.as_view()),
    path('github/issue-preview/', GithubIssuePreviewView.as_view()),
    path('transactions/', CircleTransactionListView.as_view()),
    path('transactions/<uuid:transaction_id>/', CircleTransactionStatusView.as_view()),
    path('', include(router.urls)),
]
