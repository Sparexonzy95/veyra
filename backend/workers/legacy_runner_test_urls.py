"""Test-only URL surface for the retired legacy Runner protocol.

Production deliberately does not include these URLs. Keeping this isolated
URLConf lets us regression-test the internal compatibility implementation
without making it a public onboarding path.
"""

from django.urls import include, path


urlpatterns = [
    path("api/v1/runner/", include("workers.runner_urls")),
    path("api/v1/", include("workers.owner_urls")),
]
