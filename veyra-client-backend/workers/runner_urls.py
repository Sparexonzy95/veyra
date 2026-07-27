from django.urls import path

from workers.runner_views import RunnerHeartbeatView, RunnerPairView


urlpatterns = [
    path("pair/", RunnerPairView.as_view(), name="runner-pair"),
    path("heartbeat/", RunnerHeartbeatView.as_view(), name="runner-heartbeat"),
]
