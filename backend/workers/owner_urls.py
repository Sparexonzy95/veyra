from django.urls import include, path
from rest_framework.routers import DefaultRouter

from workers.owner_views import AgentOwnerWorkerViewSet


router = DefaultRouter()
router.register("agents", AgentOwnerWorkerViewSet, basename="agent-owner-agent")

urlpatterns = [path("", include(router.urls))]
