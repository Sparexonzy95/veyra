from django.urls import path

from workers.runtime_api_views import (
    AgentRuntimeConfigurationView,
    AgentRuntimeHeartbeatView,
)


urlpatterns = [
    path("heartbeat/", AgentRuntimeHeartbeatView.as_view(), name="agent-runtime-heartbeat"),
    path("configuration/", AgentRuntimeConfigurationView.as_view(), name="agent-runtime-configuration"),
]
