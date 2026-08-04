from django.urls import path
from wallets.webhooks import CircleWebhookView
urlpatterns = [path('circle/', CircleWebhookView.as_view())]
