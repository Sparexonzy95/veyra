from django.conf import settings
from django.test import TestCase, override_settings
from common.checks import veyra_deployment_checks


@override_settings(VEYRA_ALLOWED_ORIGINS={"http://localhost:3000"})
class CookieOriginProtectionTests(TestCase):
    def test_cookie_authenticated_mutation_requires_origin(self):
        self.client.cookies[settings.VEYRA_SESSION_COOKIE] = "session-token"

        response = self.client.post("/api/v1/auth/logout/")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["detail"],
            "Origin is required for cookie-authenticated changes.",
        )

    def test_cookie_authenticated_mutation_accepts_trusted_origin(self):
        self.client.cookies[settings.VEYRA_SESSION_COOKIE] = "invalid-session-token"

        response = self.client.post(
            "/api/v1/auth/logout/",
            HTTP_ORIGIN="http://localhost:3000",
        )

        self.assertNotEqual(
            response.json().get("detail"),
            "Origin is required for cookie-authenticated changes.",
        )


class DeploymentSafetyCheckTests(TestCase):
    @override_settings(
        DEBUG=False,
        SECRET_KEY="dev-only-change-me",
        SESSION_COOKIE_SECURE=False,
    )
    def test_insecure_production_defaults_are_reported(self):
        errors = veyra_deployment_checks(None)

        self.assertEqual(
            {error.id for error in errors},
            {"veyra.E001", "veyra.E002"},
        )

    def test_bearer_style_mutation_without_cookie_does_not_require_origin(self):
        response = self.client.post("/api/v1/runner/heartbeat/")

        self.assertNotEqual(response.status_code, 403)
