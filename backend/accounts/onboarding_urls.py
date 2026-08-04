from django.urls import path

from accounts.views import AgentOwnerOnboardingView, ClientOnboardingView


urlpatterns = [
    path('client/', ClientOnboardingView.as_view()),
    path('agent-owner/', AgentOwnerOnboardingView.as_view()),
]
