from django.urls import path

from jobs.github_views import GitHubWebhookView

urlpatterns = [
    path("github/", GitHubWebhookView.as_view(), name="github-webhook"),
]
