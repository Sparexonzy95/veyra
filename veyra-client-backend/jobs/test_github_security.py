from unittest.mock import Mock

from django.test import SimpleTestCase

from jobs.github import _manifest_text


class GitHubManifestSecurityTests(SimpleTestCase):
    def test_download_url_must_use_approved_github_host(self):
        client = Mock()

        result = _manifest_text(
            client,
            {
                "download_url": "http://127.0.0.1/internal/credentials",
            },
        )

        self.assertEqual(result, "")
        client.get.assert_not_called()

    def test_download_does_not_follow_redirects(self):
        response = Mock(is_success=True, text="pytest==8.0")
        client = Mock()
        client.get.return_value = response

        result = _manifest_text(
            client,
            {
                "download_url": (
                    "https://raw.githubusercontent.com/org/repo/main/requirements.txt"
                ),
            },
        )

        self.assertEqual(result, "pytest==8.0")
        client.get.assert_called_once_with(
            "https://raw.githubusercontent.com/org/repo/main/requirements.txt",
            timeout=12,
            follow_redirects=False,
        )
