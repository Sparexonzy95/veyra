from django.urls import path
from accounts.views import ClientOnboardingView

urlpatterns = [path('client/', ClientOnboardingView.as_view())]
