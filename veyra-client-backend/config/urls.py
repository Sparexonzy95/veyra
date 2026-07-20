from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from common.views import HealthView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/health/', HealthView.as_view(), name='health'),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='docs'),
    path('api/v1/auth/', include('accounts.auth_urls')),
    path('api/v1/onboarding/', include('accounts.onboarding_urls')),
    path('api/v1/client/', include('wallets.urls')),
    path('api/v1/client/', include('jobs.urls')),
    path('api/v1/webhooks/', include('wallets.webhook_urls')),
]
