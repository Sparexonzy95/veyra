from django.urls import path

from workers.runtime_api_views import (
    AgentRuntimeConfigurationView,
    AgentRuntimeHeartbeatView,
    AgentRuntimeJobCredentialView,
    AgentRuntimeJobResultView,
    AgentRuntimeQualificationSubmitView,
    AgentRuntimeVerificationCredentialView,
    AgentRuntimeVerificationResultView,
)


urlpatterns = [
    path("heartbeat/", AgentRuntimeHeartbeatView.as_view(), name="agent-runtime-heartbeat"),
    path("configuration/", AgentRuntimeConfigurationView.as_view(), name="agent-runtime-configuration"),
    path(
        "qualification/submit/",
        AgentRuntimeQualificationSubmitView.as_view(),
        name="agent-runtime-qualification-submit",
    ),
    path(
        "job/credential/",
        AgentRuntimeJobCredentialView.as_view(),
        name="agent-runtime-job-credential",
    ),
    path(
        "job/result/",
        AgentRuntimeJobResultView.as_view(),
        name="agent-runtime-job-result",
    ),
    path(
        "verification/credential/",
        AgentRuntimeVerificationCredentialView.as_view(),
        name="agent-runtime-verification-credential",
    ),
    path(
        "verification/result/",
        AgentRuntimeVerificationResultView.as_view(),
        name="agent-runtime-verification-result",
    ),
]
