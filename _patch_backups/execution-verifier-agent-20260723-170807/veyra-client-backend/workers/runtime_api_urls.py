from django.urls import path

from workers.runtime_api_views import (
    AgentRuntimeConfigurationView,
    AgentRuntimeHeartbeatView,
    AgentRuntimeQualificationSubmitView,
)


urlpatterns = [
    path("heartbeat/", AgentRuntimeHeartbeatView.as_view(), name="agent-runtime-heartbeat"),
    path("configuration/", AgentRuntimeConfigurationView.as_view(), name="agent-runtime-configuration"),
    path(
        "qualification/submit/",
        AgentRuntimeQualificationSubmitView.as_view(),
        name="agent-runtime-qualification-submit",
    ),
]
