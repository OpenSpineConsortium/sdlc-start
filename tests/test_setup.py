"""scripts/setup.py applies the template's settings as the Setup App and
reports each one.

The report is what the pull request renders, so it carries GitHub's words;
the log is public, so it carries none. Each setting stands on its own: one
GitHub refuses costs itself and nothing else. Mode existing drops the rule
that requires the check, which a repository the template did not make has
no job for, and a ruleset of the template's name that the repository has
already is left as it is.
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))

import adopt  # noqa: E402
import setup  # noqa: E402

REPO = "octo-org/widget"
# The shape of the template's docs/setup/ruleset-main.json, with the rule
# mode existing drops and two it keeps.
RULESET = {
    "name": "Protect the default branch",
    "target": "branch",
    "enforcement": "active",
    "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
    "rules": [
        {"type": "deletion"},
        {"type": "pull_request", "parameters": {"required_approving_review_count": 0}},
        {"type": "required_status_checks",
         "parameters": {"strict_required_status_checks_policy": True,
                        "required_status_checks": [{"context": "check"}]}},
    ],
    "bypass_actors": [],
}
TOGGLES = {"delete_branch_on_merge": True, "allow_auto_merge": True}
SCANNING = {"security_and_analysis": {"secret_scanning": {"status": "enabled"}}}
PUSH_PROTECTION = {"security_and_analysis": {"secret_scanning_push_protection": {"status": "enabled"}}}
REFUSED = (422, {"message": "Secret scanning is not available for this repository.",
                 "errors": [{"message": "Upgrade the plan."}]})


class FakeGitHub:
    """A transport that answers from a table keyed (method, path) and keeps
    every call; the default answers are a public repository with no
    ruleset that accepts every write."""

    def __init__(self, answers=None, raising=None):
        self.answers = answers or {}
        self.raising = raising
        self.calls = []

    def __call__(self, method, url, headers, body):
        path = url.removeprefix(setup.API)
        self.calls.append((method, path, headers, body))
        if self.raising:
            raise setup.GitHubError(self.raising)
        if (method, path) in self.answers:
            status, answer = self.answers[(method, path)]
        elif (method, path) == ("GET", f"/repos/{REPO}"):
            status, answer = 200, {"private": False}
        elif (method, path) == ("GET", f"/repos/{REPO}/rulesets?includes_parents=false"):
            status, answer = 200, []
        elif method == "POST":
            status, answer = 201, {"id": 1}
        else:
            status, answer = 200, {}
        return status, json.dumps(answer).encode("utf-8")

    def writes(self):
        return [(method, path, body) for method, path, _, body in self.calls if method in ("POST", "PATCH")]


class Apply(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.ruleset = self.root / "ruleset-main.json"
        self.ruleset.write_text(json.dumps(RULESET, indent=2) + "\n", encoding="utf-8")
        self.report = self.root / "settings.json"
        patcher = mock.patch.dict(os.environ, {"GH_TOKEN": "ghs_token_for_tests"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def apply(self, github, mode="new", ruleset=None):
        """Run apply; (exit code, the report or None, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        argv = ["apply", "--repo", REPO, "--mode", mode, "--ruleset", str(ruleset or self.ruleset),
                "--report", str(self.report)]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = setup.main(argv, transport=github)
        report = json.loads(self.report.read_text(encoding="utf-8")) if self.report.exists() else None
        return code, report, out.getvalue(), err.getvalue()

    def states(self, report):
        return {key: setting["state"] for key, setting in report["settings"].items()}

    def test_new_mode_applies_every_setting_in_order(self):
        github = FakeGitHub()
        code, report, out, err = self.apply(github)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(github.writes(), [
            ("POST", f"/repos/{REPO}/rulesets", RULESET),
            ("PATCH", f"/repos/{REPO}", TOGGLES),
            ("PATCH", f"/repos/{REPO}", SCANNING),
            ("PATCH", f"/repos/{REPO}", PUSH_PROTECTION),
        ])
        self.assertEqual(report["schema"], setup.REPORT_SCHEMA)
        self.assertEqual((report["outcome"], report["mode"], report["private"]), ("applied", "new", False))
        self.assertEqual((report["ruleset_name"], report["required_check"]), ("Protect the default branch", True))
        self.assertEqual(self.states(report), {
            "ruleset": "done", "toggles": "done", "secret_scanning": "done", "push_protection": "done",
        })
        self.assertEqual(out.splitlines(), [
            "settings: ruleset: created",
            "settings: delete head branches on merge, allow auto-merge: on",
            "settings: secret scanning: on",
            "settings: push protection: on",
        ])

    def test_every_call_carries_the_token_and_the_api_version(self):
        github = FakeGitHub()
        self.apply(github)
        for method, path, headers, body in github.calls:
            with self.subTest(call=(method, path)):
                self.assertEqual(headers["Authorization"], "Bearer ghs_token_for_tests")
                self.assertEqual(headers["X-GitHub-Api-Version"], setup.API_VERSION)
                self.assertEqual(headers["Accept"], "application/vnd.github+json")
                self.assertEqual("Content-Type" in headers, body is not None)

    def test_existing_mode_drops_the_rule_that_requires_the_check(self):
        github = FakeGitHub()
        code, report, _, _ = self.apply(github, mode="existing")
        self.assertEqual(code, 0)
        posted = github.writes()[0][2]
        self.assertEqual([rule["type"] for rule in posted["rules"]], ["deletion", "pull_request"])
        self.assertEqual(posted["name"], RULESET["name"])
        self.assertFalse(report["required_check"])
        self.assertEqual(report["mode"], "existing")
        self.assertEqual(json.loads(self.ruleset.read_text())["rules"], RULESET["rules"])

    def test_a_ruleset_of_that_name_is_left_as_it_is(self):
        listed = {("GET", f"/repos/{REPO}/rulesets?includes_parents=false"): (200, [{"name": RULESET["name"]}])}
        github = FakeGitHub(listed)
        code, report, out, _ = self.apply(github)
        self.assertEqual(code, 0)
        self.assertNotIn("POST", [method for method, _, _ in github.writes()])
        self.assertEqual(self.states(report)["ruleset"], "exists")
        self.assertIn("settings: ruleset: exists, left as it is", out)

    def test_an_organizations_ruleset_of_that_name_is_not_this_repositorys(self):
        """The list is asked without parents: a ruleset the organization set
        is not the repository's own, so the repository gets one."""
        github = FakeGitHub()
        self.apply(github)
        self.assertIn(("GET", f"/repos/{REPO}/rulesets?includes_parents=false"),
                      [(method, path) for method, path, _, _ in github.calls])
        self.assertEqual(github.writes()[0][0], "POST")

    def test_a_private_repository_is_noted_and_an_internal_one_is_not(self):
        """The note about GitHub Free is for a private repository; an
        internal one, which GitHub flags private too, is an enterprise's."""
        github = FakeGitHub({("GET", f"/repos/{REPO}"): (200, {"private": True, "visibility": "private"})})
        _, report, _, _ = self.apply(github)
        self.assertTrue(report["private"])
        github = FakeGitHub({("GET", f"/repos/{REPO}"): (200, {"private": True, "visibility": "internal"})})
        _, report, _, _ = self.apply(github)
        self.assertFalse(report["private"])

    def test_a_redirect_is_a_refusal_not_a_setting_done(self):
        """urllib would repeat a redirected POST as a GET of the new place
        and report its 200; the transport hands every 3xx back as it is,
        and a 3xx is not done."""
        class Github(FakeGitHub):
            def __call__(self, method, url, headers, body):
                if method in ("POST", "PATCH"):
                    self.calls.append((method, url.removeprefix(setup.API), headers, body))
                    return 307, b'{"message": "Temporary Redirect"}'
                return super().__call__(method, url, headers, body)

        _, report, out, _ = self.apply(Github())
        self.assertEqual(self.states(report), {
            "ruleset": "failed", "toggles": "failed", "secret_scanning": "failed", "push_protection": "not-tried",
        })
        self.assertEqual(report["settings"]["toggles"]["detail"], "HTTP 307: Temporary Redirect")
        self.assertNotIn("on", out.splitlines()[1].split(": ")[-1])
        self.assertIsNone(setup.NoRedirect().redirect_request(None, None, 301, "", {}, "https://elsewhere.example"))
        self.assertTrue(any(isinstance(handler, setup.NoRedirect) for handler in setup.OPENER.handlers))

    def test_an_answer_that_is_not_json_is_a_refusal_with_the_report_still_written(self):
        class Github(FakeGitHub):
            def __call__(self, method, url, headers, body):
                if method == "POST":
                    self.calls.append((method, url.removeprefix(setup.API), headers, body))
                    return 201, b"<html>created, says a proxy</html>"
                return super().__call__(method, url, headers, body)

        code, report, _, err = self.apply(Github())
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(report["settings"]["ruleset"]["detail"], "HTTP 201: GitHub's answer was not JSON")
        self.assertEqual(self.states(report)["toggles"], "done")

    def test_a_validation_error_without_a_message_keeps_its_field_and_code(self):
        class Github(FakeGitHub):
            def __call__(self, method, url, headers, body):
                if method == "POST":
                    self.calls.append((method, url.removeprefix(setup.API), headers, body))
                    return 422, json.dumps({"message": "Validation Failed", "errors": [
                        {"resource": "Ruleset", "field": "name", "code": "already_exists"}]}).encode("utf-8")
                return super().__call__(method, url, headers, body)

        _, report, _, _ = self.apply(Github())
        self.assertEqual(report["settings"]["ruleset"]["detail"],
                         "HTTP 422: Validation Failed Ruleset name already_exists")

    def test_secret_scanning_refused_costs_itself_and_push_protection_only(self):
        class Github(FakeGitHub):
            def __call__(self, method, url, headers, body):
                if method == "PATCH" and body == SCANNING:
                    self.calls.append((method, url.removeprefix(setup.API), headers, body))
                    return REFUSED[0], json.dumps(REFUSED[1]).encode("utf-8")
                return super().__call__(method, url, headers, body)

        github = Github()
        code, report, out, _ = self.apply(github)
        self.assertEqual(code, 0)
        self.assertEqual(self.states(report), {
            "ruleset": "done", "toggles": "done", "secret_scanning": "failed", "push_protection": "not-tried",
        })
        self.assertEqual(report["settings"]["secret_scanning"]["detail"],
                         "HTTP 422: Secret scanning is not available for this repository. Upgrade the plan.")
        self.assertEqual(report["settings"]["push_protection"]["detail"], "secret scanning is not on")
        self.assertNotIn(PUSH_PROTECTION, [body for _, _, body in github.writes()])
        self.assertIn("settings: secret scanning: not turned on", out)
        self.assertIn("settings: push protection: not tried", out)
        self.assertNotIn("Upgrade", out)
        self.assertNotIn("422", out)

    def test_push_protection_refused_after_scanning(self):
        class Github(FakeGitHub):
            def __call__(self, method, url, headers, body):
                if method == "PATCH" and body == PUSH_PROTECTION:
                    self.calls.append((method, url.removeprefix(setup.API), headers, body))
                    return 422, b'{"message": "Push protection is not available."}'
                return super().__call__(method, url, headers, body)

        _, report, out, _ = self.apply(Github())
        self.assertEqual(self.states(report)["secret_scanning"], "done")
        self.assertEqual(self.states(report)["push_protection"], "failed")
        self.assertEqual(report["settings"]["push_protection"]["detail"], "HTTP 422: Push protection is not available.")
        self.assertIn("settings: push protection: not turned on", out)

    def test_a_token_github_refuses_fails_each_setting_and_nothing_else(self):
        class Github(FakeGitHub):
            def __call__(self, method, url, headers, body):
                self.calls.append((method, url.removeprefix(setup.API), headers, body))
                return 403, b'{"message": "Resource not accessible by integration"}'

        github = Github()
        code, report, out, err = self.apply(github)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.states(report), {
            "ruleset": "failed", "toggles": "failed", "secret_scanning": "failed", "push_protection": "not-tried",
        })
        self.assertIsNone(report["private"])
        for key in ("ruleset", "toggles", "secret_scanning"):
            self.assertEqual(report["settings"][key]["detail"], "HTTP 403: Resource not accessible by integration")
        self.assertEqual(out.splitlines(), [
            "settings: ruleset: not created",
            "settings: the two toggles: not changed",
            "settings: secret scanning: not turned on",
            "settings: push protection: not tried",
        ])
        self.assertNotIn("integration", out)

    def test_github_out_of_reach_is_a_failure_with_a_reason(self):
        code, report, out, _ = self.apply(FakeGitHub(raising="GitHub could not be reached (URLError)"))
        self.assertEqual(code, 0)
        self.assertEqual(report["settings"]["ruleset"]["detail"], "GitHub could not be reached (URLError)")
        self.assertNotIn("URLError", out)

    def test_a_refusal_with_no_json_body_keeps_the_status(self):
        class Github(FakeGitHub):
            def __call__(self, method, url, headers, body):
                self.calls.append((method, url.removeprefix(setup.API), headers, body))
                return 502, b"<html>bad gateway</html>"

        _, report, _, _ = self.apply(Github())
        self.assertEqual(report["settings"]["ruleset"]["detail"], "HTTP 502")

    def test_githubs_words_are_one_line_and_bounded(self):
        class Github(FakeGitHub):
            def __call__(self, method, url, headers, body):
                self.calls.append((method, url.removeprefix(setup.API), headers, body))
                return 422, json.dumps({"message": "first line\nsecond line " + "x" * 1000}).encode("utf-8")

        _, report, _, _ = self.apply(Github())
        detail = report["settings"]["ruleset"]["detail"]
        self.assertNotIn("\n", detail)
        self.assertLessEqual(len(detail), setup.DETAIL_LENGTH)
        self.assertTrue(detail.startswith("HTTP 422: first line second line x"))
        self.assertTrue(detail.endswith("..."))

    def test_a_ruleset_file_that_cannot_be_read_costs_the_ruleset_only(self):
        github = FakeGitHub()
        code, report, out, _ = self.apply(github, ruleset=self.root / "missing.json")
        self.assertEqual(code, 0)
        self.assertEqual(self.states(report)["ruleset"], "failed")
        self.assertEqual(report["settings"]["ruleset"]["detail"],
                         "the template's ruleset file could not be read, so no ruleset was made")
        self.assertIsNone(report["ruleset_name"])
        self.assertEqual([method for method, _, _ in github.writes()], ["PATCH", "PATCH", "PATCH"])
        self.assertIn("settings: ruleset: not created", out)
        self.ruleset.write_text('{"name": "x"}\n', encoding="utf-8")
        code, report, _, _ = self.apply(FakeGitHub())
        self.assertEqual((code, self.states(report)["ruleset"]), (0, "failed"))

    def test_no_token_is_an_error_and_writes_no_report(self):
        with mock.patch.dict(os.environ, {"GH_TOKEN": ""}):
            code, report, _, err = self.apply(FakeGitHub())
        self.assertEqual((code, report), (2, None))
        self.assertIn("GH_TOKEN", err)

    def test_a_repository_name_that_is_not_one_is_an_error(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = setup.main(["apply", "--repo", "a/b; rm -rf /", "--mode", "new", "--ruleset", str(self.ruleset),
                               "--report", str(self.report)], transport=FakeGitHub())
        self.assertEqual(code, 2)
        self.assertFalse(self.report.exists())

    def test_the_report_is_one_the_body_reads(self):
        self.apply(FakeGitHub())
        self.assertEqual(adopt.read_report(self.report)["outcome"], "applied")
        self.apply(FakeGitHub({("GET", f"/repos/{REPO}"): (401, {"message": "Bad credentials"})}))
        self.assertEqual(adopt.read_report(self.report)["settings"]["toggles"]["state"], "done")


class Transport(unittest.TestCase):
    def test_a_body_cut_short_is_a_failure_to_get_an_answer(self):
        """http.client's own errors are not OSErrors; one escaping the
        transport would end the run before the report."""
        import http.client

        def opening(request, timeout):
            raise http.client.IncompleteRead(b"partial")

        with mock.patch.object(setup.OPENER, "open", opening):
            with self.assertRaises(setup.GitHubError) as caught:
                setup.urllib_transport("GET", "https://api.github.com/repos/o/r", {}, None)
        self.assertIn("IncompleteRead", str(caught.exception))

    def test_a_refusal_whose_body_is_cut_short_is_the_same_failure(self):
        import http.client
        import urllib.error

        class CutShort:
            def read(self):
                raise http.client.IncompleteRead(b"par")

        def opening(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 502, "Bad Gateway", {}, CutShort())

        with mock.patch.object(setup.OPENER, "open", opening):
            with self.assertRaises(setup.GitHubError):
                setup.urllib_transport("GET", "https://api.github.com/repos/o/r", {}, None)


class Skip(unittest.TestCase):
    def test_skip_writes_why_nothing_was_applied(self):
        self.assertEqual(setup.WHYS, ("not-set-up", "not-installed", "front-door-broken", "not-reported"))
        with tempfile.TemporaryDirectory() as scratch:
            report = Path(scratch) / "settings.json"
            for why in setup.WHYS:
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = setup.main(["skip", "--why", why, "--mode", "existing", "--report", str(report)])
                self.assertEqual(code, 0)
                written = json.loads(report.read_text(encoding="utf-8"))
                self.assertEqual((written["schema"], written["outcome"], written["mode"], written["settings"]),
                                 (setup.REPORT_SCHEMA, why, "existing", {}))
                self.assertEqual(out.getvalue(), f"settings: none applied ({why})\n")
                self.assertEqual(adopt.read_report(report)["outcome"], why)

    def test_a_reason_that_is_not_one_is_refused(self):
        with self.assertRaises(SystemExit):
            setup.parse_args(["skip", "--why", "applied", "--mode", "new", "--report", "x"])


class Messages(unittest.TestCase):
    def test_githubs_message_and_errors_become_one_line(self):
        data = json.dumps({"message": "Validation  Failed", "errors": [{"message": "a\nb"}, "plain", {"code": "x"}]})
        self.assertEqual(setup.github_message(data.encode("utf-8")), "Validation Failed a b plain x")
        self.assertEqual(setup.github_message(b"not json"), "")
        self.assertEqual(setup.github_message(b"[1, 2]"), "")
        self.assertEqual(setup.github_message(b'{"message": ""}'), "")


if __name__ == "__main__":
    unittest.main()
