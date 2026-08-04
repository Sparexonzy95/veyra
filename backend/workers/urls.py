from django.urls import include, path
from rest_framework.routers import DefaultRouter

from workers.views import WorkerAgentViewSet


router = DefaultRouter()
router.register("agents", WorkerAgentViewSet, basename="worker-agent")

urlpatterns = [path("", include(router.urls))]