from django.test import SimpleTestCase

from workers.execution_transport import _path_matches_policy_rule


class ExecutionPolicyGlobTests(SimpleTestCase):
    def test_recursive_allowed_rule_matches_nested_file(self):
        self.assertTrue(_path_matches_policy_rule("tests/test_app.py", "tests/**"))
        self.assertTrue(_path_matches_policy_rule("tests/unit/test_health.py", "tests/**"))

    def test_recursive_rule_does_not_escape_prefix(self):
        self.assertFalse(_path_matches_policy_rule("docs/test_health.py", "tests/**"))

    def test_exact_file_rule_stays_exact_or_child_prefix(self):
        self.assertTrue(_path_matches_policy_rule("app.py", "app.py"))
        self.assertFalse(_path_matches_policy_rule("pp.py", "app.py"))
