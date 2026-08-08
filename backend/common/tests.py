from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from common.checks import veyra_deployment_checks
from common.pagination import VeyraPageNumberPagination


class VeyraPageNumberPaginationTests(SimpleTestCase):
    """The paging behaviour every dashboard list depends on."""

    def setUp(self):
        self.paginator = VeyraPageNumberPagination()
        self.factory = APIRequestFactory()
        self.records = list(range(250))

    def _page(self, query):
        request = Request(self.factory.get(f"/api/v1/agents/{query}"))
        return self.paginator.paginate_queryset(self.records, request)

    def test_default_page_size_is_twenty(self):
        self.assertEqual(len(self._page("")), 20)

    def test_page_size_query_param_is_honoured(self):
        """The regression this class exists for.

        The frontend already requested ``?page_size=100``. Because the old
        configuration set only PAGE_SIZE, DRF ignored the parameter and
        returned 20 records, silently dropping the rest of the list.
        """
        self.assertEqual(len(self._page("?page_size=6")), 6)
        self.assertEqual(len(self._page("?page_size=100")), 100)

    def test_page_size_is_capped_at_max(self):
        """A caller cannot turn paging off by asking for everything."""
        self.assertEqual(len(self._page("?page_size=100000")), 100)

    def test_page_selects_the_expected_slice(self):
        self.assertEqual(self._page("?page=2&page_size=6"), list(range(6, 12)))

    def test_invalid_page_size_falls_back_to_default(self):
        self.assertEqual(len(self._page("?page_size=abc")), 20)


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
