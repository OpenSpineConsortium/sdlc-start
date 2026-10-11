"""scripts/sweep.py lists the App's installations and writes the repositories
to adopt.

The log is public, so the summary carries counts and never a name; the
candidates file carries ids and a mode, each line written as it is found.
Every skip has one reason and a check that answers neither yes nor a clean
404 skips the repository rather than ending the sweep. The JWT reaches the
App's endpoints only, and each installation's token its own repositories,
then is revoked. The clock is the fake GitHub's, so the grace, the budget
and the rotation are pinned.
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))

import sweep  # noqa: E402

JWT = "eyJ.app.jwt-for-tests"
TOKEN = "ghs_installation_token_for_tests"
# What an installation carries once its owner accepted every permission the
# adoption run asks for.
PERMISSIONS = {"contents": "write", "issues": "write", "pull_requests": "write", "workflows": "write",
               "metadata": "read"}
# The clock's reading unless a test moves it: a multiple of ten minutes
# that leaves the sweep starting at the first installation for any list
# of up to six, so the tests that care nothing for the rotation read in
# the order they list.
NOW = 1_728_000_000
# Long before NOW: no installation is fresh unless a test dates it so.
INSTALLED = "2024-01-01T00:00:00Z"
SLUG = "openspine-sdlc"
BOT = "openspine-sdlc%5Bbot%5D"


def moment(seconds_before_now):
    """A date as GitHub writes one, this long before NOW."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - seconds_before_now))


def installation(number=77, login="mona", owner_type="User", permissions=PERMISSIONS, **more):
    fields = {"id": number, "account": {"login": login, "type": owner_type}, "permissions": dict(permissions),
              "repository_selection": "selected", "created_at": INSTALLED, "updated_at": INSTALLED}
    fields.update(more)
    return fields


INSTALLATION = installation()
APP = "/app"
INSTALLATIONS = "/app/installations?per_page=100"
REPOSITORIES = "/installation/repositories?per_page=100"
NOT_FOUND = (404, {"message": "Not Found"})
# Every name here must stay out of the log; the summary test checks that.
NAMES = ("mona", "widget", "octo-org", "gadget", "hubot", SLUG)


def repository(full_name="mona/widget", number=4242, owner_type="User", **more):
    owner = full_name.split("/")[0]
    fields = {"id": number, "full_name": full_name, "owner": {"login": owner, "type": owner_type},
              "default_branch": "main", "archived": False, "fork": False, "private": False}
    fields.update(more)
    return fields


REPOSITORY = repository()
ORG_REPOSITORY = repository("octo-org/gadget", 5151, "Organization")
# The two checks that read what an earlier offer left behind, for the
# default repository.
DECLINED = "pulls?state=closed&head=mona:sdlc/adopt&per_page=1"
REFUSED = f"issues?state=open&creator={BOT}&per_page=100"


def tree(*paths, truncated=False):
    """A git tree as GitHub lists it; a path ending in / is a folder."""
    entries = []
    for path in paths:
        if path.endswith("/"):
            entries.append({"path": path.rstrip("/"), "type": "tree", "mode": "040000"})
        else:
            entries.append({"path": path, "type": "blob", "mode": "100644"})
    return {"sha": "abc", "tree": entries, "truncated": truncated}


def repo_path(repo, rest):
    return f"/repos/{repo['full_name']}/{rest}"


def refusal(title=sweep.REFUSAL_TITLE, **more):
    """An issue as the list endpoint gives it, the App's bot its author."""
    return {"number": 3, "title": title, "state": "open", "user": {"login": f"{SLUG}[bot]", "type": "Bot"}, **more}


class FakeGitHub:
    """A transport that answers from a table keyed (method, path) and keeps
    every call; by default it knows one App with one installation holding
    one repository whose only file is a README, with no offer behind it.
    An entry is (status, answer) or (status, answer, Link header). It is
    also the clock: the sweep reads now() from it, and each call may move
    it on, so the budget is spent by calls and not by waiting."""

    def __init__(self, answers=None, repositories=(REPOSITORY,), installations=(INSTALLATION,), raising=None,
                 start=NOW, seconds_per_call=0):
        self.answers = dict(answers or {})
        self.repositories = list(repositories)
        self.installations = list(installations)
        self.raising = raising
        self.time = start
        self.seconds_per_call = seconds_per_call
        self.calls = []

    def now(self):
        return self.time

    def __call__(self, method, url, headers, body):
        path = url.removeprefix(sweep.API)
        self.calls.append((method, path, headers, body))
        self.time += self.seconds_per_call
        if self.raising:
            raise sweep.GitHubError(self.raising)
        status, answer, *link = self.answers.get((method, path)) or self.default(method, path)
        replied = {"Link": link[0]} if link else {}
        return status, replied, b"" if answer is None else json.dumps(answer).encode("utf-8")

    def default(self, method, path):
        if path == APP:
            return 200, {"id": 1, "slug": SLUG, "name": "OpenSpine SDLC"}
        if path == INSTALLATIONS:
            return 200, self.installations
        if method == "POST" and path.startswith("/app/installations/") and path.endswith("/access_tokens"):
            return 201, {"token": TOKEN}
        if path == REPOSITORIES:
            return 200, {"total_count": len(self.repositories), "repositories": self.repositories}
        if (method, path) == ("DELETE", "/installation/token"):
            return 204, None
        if "/branches/" in path:
            return 200, {"name": "main"}
        if "/git/matching-refs/heads/sdlc/adopt" in path:
            return 200, []
        if "/contents/" in path:
            return NOT_FOUND
        if "/pulls?" in path or "/issues?" in path:
            return 200, []
        if "/git/trees/" in path:
            return 200, tree("README.md")
        return NOT_FOUND

    def paths(self, method=None):
        return [path for called, path, _, _ in self.calls if method in (None, called)]


class Sweep(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.out = Path(self.scratch.name) / "candidates.tsv"
        patcher = mock.patch.dict(os.environ, {"APP_JWT": JWT})
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_sweep(self, github, *more, own=None):
        """Run the sweep on the fake GitHub's clock, with any more options;
        (exit code, the file's text or None, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        argv = ["--out", str(self.out)] + (["--own", own] if own else []) + list(more)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sweep.main(argv, transport=github, now=github.now)
        written = self.out.read_text(encoding="utf-8") if self.out.exists() else None
        return code, written, out.getvalue(), err.getvalue()

    def skipped(self, github, repo, answers=None):
        """The summary's parenthesis for one repository with these answers."""
        code, written, out, err = self.run_sweep(FakeGitHub(answers, repositories=[repo]))
        self.assertEqual((code, written, err), (0, "", ""))
        self.assertIn("1 repository, 0 candidates, 1 skipped (", out)
        return out.split("(", 1)[1].rstrip(")\n")

    def candidate(self, answers):
        """The default repository is a candidate under these answers."""
        code, written, out, err = self.run_sweep(FakeGitHub(answers))
        self.assertEqual((code, written, err), (0, "77\t4242\tnew\n", ""))
        self.assertIn("1 candidate, 0 skipped", out)

    def pending_file(self, *names):
        path = Path(self.scratch.name) / "pending"
        path.write_text("".join(f"{name}\n" for name in names), encoding="utf-8")
        return str(path)

    # -- the candidate and the summary --

    def test_a_candidate_is_one_line_of_three_columns(self):
        code, written, out, err = self.run_sweep(FakeGitHub())
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(written, "77\t4242\tnew\n")
        self.assertEqual(out, "sweep: 1 installation, 1 repository, 1 candidate, 0 skipped\n")

    def test_the_summary_counts_and_names_nothing(self):
        private = repository("octo-org/gadget", 5151, "Organization", private=True)
        answers = {("GET", repo_path(private, "contents/docs/agents/PROTOCOL.md")): (200, {"name": "PROTOCOL.md"})}
        github = FakeGitHub(answers, repositories=[REPOSITORY, private, repository("hubot/widget", 6, archived=True)])
        code, written, out, err = self.run_sweep(github)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, "sweep: 1 installation, 3 repositories, 1 candidate, 2 skipped (1 adopted, 1 archived)\n")
        self.assertEqual(written, "77\t4242\tnew\n")
        for name in NAMES:
            self.assertNotIn(name, out)
            self.assertNotIn(name, written)
        self.assertNotIn(JWT, out + written)
        self.assertNotIn(TOKEN, out + written)

    def test_reasons_are_listed_in_alphabetical_order_with_their_counts(self):
        repositories = [repository("octo-org/a", 1, archived=True), repository("octo-org/b", 2, archived=True),
                        repository("OpenSpineConsortium/sdlc-start", 3)]
        _, _, out, _ = self.run_sweep(FakeGitHub(repositories=repositories))
        self.assertEqual(out, "sweep: 1 installation, 3 repositories, 0 candidates, 3 skipped (2 archived, 1 own)\n")

    def test_no_candidates_writes_an_empty_file(self):
        code, written, out, _ = self.run_sweep(FakeGitHub(repositories=[]))
        self.assertEqual((code, written), (0, ""))
        self.assertEqual(out, "sweep: 1 installation, 0 repositories, 0 candidates, 0 skipped\n")
        code, written, out, _ = self.run_sweep(FakeGitHub(installations=[]))
        self.assertEqual((code, written), (0, ""))
        self.assertEqual(out, "sweep: 0 installations, 0 repositories, 0 candidates, 0 skipped\n")

    # -- every skip --

    def test_the_organizations_own_repositories_are_skipped_without_a_call(self):
        own = repository("OpenSpineConsortium/sdlc-template", 9)
        github = FakeGitHub(repositories=[own])
        _, written, out, _ = self.run_sweep(github)
        self.assertEqual(written, "")
        self.assertIn("1 skipped (1 own)", out)
        self.assertEqual([path for path in github.paths() if path.startswith("/repos/")], [])
        self.assertEqual(self.skipped(FakeGitHub(), repository("openspineconsortium/coordbench", 9)), "1 own")

    def test_own_is_the_owner_the_option_names(self):
        code, written, out, _ = self.run_sweep(FakeGitHub(repositories=[ORG_REPOSITORY, REPOSITORY]), own="Octo-Org")
        self.assertEqual((code, written), (0, "77\t4242\tnew\n"))
        self.assertIn("1 skipped (1 own)", out)

    def test_an_archived_repository_is_skipped(self):
        self.assertEqual(self.skipped(None, repository(archived=True)), "1 archived")

    def test_a_repository_of_an_open_request_is_left_to_the_form_without_a_call(self):
        """The front door's open requests name their repositories; the
        form's run has those, whatever their case on the form."""
        pending = self.pending_file("Octo-Org/Gadget", "", "  mona/WIDGET  ")
        github = FakeGitHub(repositories=[REPOSITORY, ORG_REPOSITORY, repository("hubot/widget", 6)])
        code, written, out, err = self.run_sweep(github, "--pending", pending)
        self.assertEqual((code, written, err), (0, "77\t6\tnew\n", ""))
        self.assertEqual(out, "sweep: 1 installation, 3 repositories, 1 candidate, 2 skipped (2 pending)\n")
        self.assertEqual([path for path in github.paths() if path.startswith("/repos/") and "hubot" not in path], [])
        # Without the option, or with an empty file, nothing is pending.
        self.candidate(None)
        code, written, _, _ = self.run_sweep(FakeGitHub(), "--pending", self.pending_file())
        self.assertEqual((code, written), (0, "77\t4242\tnew\n"))

    def test_a_pending_file_that_cannot_be_read_is_an_error_before_any_call(self):
        github = FakeGitHub()
        code, written, out, err = self.run_sweep(github, "--pending", str(Path(self.scratch.name) / "missing"))
        self.assertEqual((code, written, out), (2, None, ""))
        self.assertTrue(err.startswith("sweep: "))
        self.assertEqual(err.count("\n"), 1)
        self.assertEqual(github.calls, [])

    def test_a_repository_with_no_commit_is_skipped(self):
        answers = {("GET", repo_path(REPOSITORY, "branches/main")): NOT_FOUND}
        self.assertEqual(self.skipped(None, REPOSITORY, answers), "1 no commit")

    def test_a_repository_with_the_branch_sdlc_adopt_is_skipped(self):
        matching = ("GET", repo_path(REPOSITORY, "git/matching-refs/heads/sdlc/adopt"))
        exact = {matching: (200, [{"ref": "refs/heads/sdlc/adopt-again"}, {"ref": "refs/heads/sdlc/adopt"}])}
        self.assertEqual(self.skipped(None, REPOSITORY, exact), "1 offered")
        prefix_only = {matching: (200, [{"ref": "refs/heads/sdlc/adopt-again"}])}
        self.candidate(prefix_only)

    def test_an_adopted_repository_is_skipped(self):
        answers = {("GET", repo_path(REPOSITORY, "contents/docs/agents/PROTOCOL.md")): (200, {"name": "PROTOCOL.md"})}
        self.assertEqual(self.skipped(None, REPOSITORY, answers), "1 adopted")

    def switch(self, content, encoding="base64"):
        return {("GET", repo_path(REPOSITORY, "contents/.github/sdlc-adopt")):
                (200, {"name": "sdlc-adopt", "encoding": encoding, "content": content})}

    def test_a_repository_whose_switch_says_off_is_skipped(self):
        self.assertEqual(self.skipped(None, REPOSITORY, self.switch("b2Zm")), "1 opted out")
        # GitHub wraps the base64 in newlines, and the word may be any case.
        self.assertEqual(self.skipped(None, REPOSITORY, self.switch("T0ZG\n")), "1 opted out")
        self.assertEqual(self.skipped(None, REPOSITORY, self.switch("ICBvZmYgIAo=\n")), "1 opted out")
        # An editor may have put a byte order mark before the word.
        self.assertEqual(self.skipped(None, REPOSITORY, self.switch("77u/b2ZmCg==")), "1 opted out")

    def test_a_switch_that_does_not_say_off_is_not_an_opt_out(self):
        for answers in (self.switch("b24="), self.switch("", "none"), self.switch("/w=="),
                        {("GET", repo_path(REPOSITORY, "contents/.github/sdlc-adopt")): (200, [{"name": "a"}])}):
            self.candidate(answers)

    def declined(self, repo=REPOSITORY):
        path = f"pulls?state=closed&head={repo['owner']['login']}:sdlc/adopt&per_page=1"
        return {("GET", repo_path(repo, path)): (200, [{"number": 1, "state": "closed", "merged_at": None}])}

    def test_a_declined_offer_is_not_made_again(self):
        """Once the adopter closes the pull request and deletes the branch,
        the branch no longer says offered; the closed pull request does."""
        self.assertEqual(self.skipped(None, REPOSITORY, self.declined()), "1 declined")
        github = FakeGitHub(self.declined())
        self.run_sweep(github)
        self.assertIn(repo_path(REPOSITORY, DECLINED), github.paths())
        self.candidate({("GET", repo_path(REPOSITORY, DECLINED)): (200, [])})

    def refused(self, *issues):
        return {("GET", repo_path(REPOSITORY, REFUSED)): (200, list(issues))}

    def test_a_repository_whose_rules_refused_the_push_waits_for_its_issue_to_close(self):
        """The adoption run opens one issue, as the App, when the push was
        refused; while it is open the sweep does not start the run again,
        and closing it re-arms the sweep. Only the exact title counts, and
        only an issue, since the list holds pull requests too."""
        self.assertEqual(self.skipped(None, REPOSITORY, self.refused(refusal())), "1 refused")
        self.assertEqual(self.skipped(None, REPOSITORY, self.refused(refusal("Other"), refusal())), "1 refused")
        for issues in ((), (refusal("Something else"),), (refusal(pull_request={"url": "x"}),),
                       (refusal(sweep.REFUSAL_TITLE.lower()),), ("odd",)):
            with self.subTest(issues=issues):
                self.candidate(self.refused(*issues))
        self.assertEqual(sweep.REFUSAL_TITLE, "OpenSpine SDLC could not open its pull request")

    def test_the_bots_login_is_the_apps_slug_read_once_per_sweep(self):
        second = installation(78, "octo-org", "Organization")
        github = FakeGitHub({("GET", APP): (200, {"id": 2, "slug": "other-app"})}, installations=[INSTALLATION, second])
        code, _, _, _ = self.run_sweep(github)
        self.assertEqual(code, 0)
        asked = repo_path(REPOSITORY, "issues?state=open&creator=other-app%5Bbot%5D&per_page=100")
        self.assertEqual(github.paths().count(asked), 2)
        self.assertEqual(github.paths().count(APP), 1)
        self.assertLess(github.paths().index(APP), github.paths().index(INSTALLATIONS))

    def test_the_checks_come_in_their_order(self):
        """An offer's leavings are read last, and the opt-out before them:
        a merged offer reads as adopted, an opt-out as opted out whatever
        else is there, and a closed offer as declined before any issue."""
        adopted = {("GET", repo_path(REPOSITORY, "contents/docs/agents/PROTOCOL.md")): (200, {"name": "PROTOCOL.md"})}
        leavings = {**self.declined(), **self.refused(refusal())}
        self.assertEqual(self.skipped(None, REPOSITORY, {**adopted, **leavings}), "1 adopted")
        self.assertEqual(self.skipped(None, REPOSITORY, {**self.switch("b2Zm"), **leavings}), "1 opted out")
        self.assertEqual(self.skipped(None, REPOSITORY, leavings), "1 declined")
        github = FakeGitHub({**self.switch("b2Zm"), **leavings})
        self.run_sweep(github)
        self.assertNotIn(repo_path(REPOSITORY, DECLINED), github.paths())
        self.assertNotIn(repo_path(REPOSITORY, REFUSED), github.paths())

    def test_a_check_that_is_refused_skips_the_repository_as_unreadable(self):
        refused = (403, {"message": "Resource not accessible by integration"})
        for rest in ("branches/main", "git/matching-refs/heads/sdlc/adopt", "contents/docs/agents/PROTOCOL.md",
                     "contents/.github/sdlc-adopt", DECLINED, REFUSED, "git/trees/main?recursive=1"):
            with self.subTest(check=rest):
                answers = {("GET", repo_path(REPOSITORY, rest)): refused}
                code, written, out, err = self.run_sweep(FakeGitHub(answers, repositories=[REPOSITORY, ORG_REPOSITORY]))
                self.assertEqual((code, written, err), (0, "77\t5151\tnew\n", ""))
                self.assertEqual(out, "sweep: 1 installation, 2 repositories, 1 candidate, 1 skipped (1 unreadable)\n")
        # A tree the repository should have but GitHub does not find is no
        # cleaner: the mode is not guessed. Nor is a list that is not one.
        answers = {("GET", repo_path(REPOSITORY, "git/trees/main?recursive=1")): NOT_FOUND}
        self.assertEqual(self.skipped(None, REPOSITORY, answers), "1 unreadable")
        for rest in (DECLINED, REFUSED, "git/matching-refs/heads/sdlc/adopt"):
            with self.subTest(check=rest):
                answers = {("GET", repo_path(REPOSITORY, rest)): (200, {"message": "odd"})}
                self.assertEqual(self.skipped(None, REPOSITORY, answers), "1 unreadable")

    def test_github_out_of_reach_mid_sweep_is_unreadable_too(self):
        class Github(FakeGitHub):
            def __call__(self, method, url, headers, body):
                if "/branches/" in url:
                    self.calls.append((method, url.removeprefix(sweep.API), headers, body))
                    raise sweep.GitHubError("GitHub could not be reached (URLError)")
                return super().__call__(method, url, headers, body)

        code, written, out, err = self.run_sweep(Github())
        self.assertEqual((code, written, err), (0, "", ""))
        self.assertIn("1 skipped (1 unreadable)", out)
        self.assertNotIn("URLError", out)

    # -- the mode --

    def test_the_tree_rule(self):
        new = [tree("README.md"), tree("README.md", "LICENSE", ".gitignore"), tree("README.rst", "COPYING"),
               tree("readme", "License.txt", ".gitattributes", ".GITIGNORE"), tree(), tree("README.en.md")]
        existing = [tree("README.md", "src/main.py"), tree("README.md", truncated=True), tree("docs/README.md"),
                    tree("LICENSE-MIT"), tree("README.md", "setup.cfg"), tree("README.md", ".github/CODEOWNERS"),
                    tree("README.md", "notes.txt")]
        for found in new:
            with self.subTest(tree=[entry["path"] for entry in found["tree"]]):
                self.assertEqual(sweep.classify_tree(found), "new")
        for found in existing:
            with self.subTest(tree=[entry["path"] for entry in found["tree"]], truncated=found["truncated"]):
                self.assertEqual(sweep.classify_tree(found), "existing")

    def test_a_folder_is_not_a_file_and_a_submodule_is_the_repositorys_own(self):
        self.assertEqual(sweep.classify_tree(tree("README.md", "docs/")), "new")
        submodule = tree("README.md")
        submodule["tree"].append({"path": "vendor", "type": "commit", "mode": "160000"})
        self.assertEqual(sweep.classify_tree(submodule), "existing")
        self.assertEqual(sweep.classify_tree({"sha": "abc"}), "existing")
        self.assertEqual(sweep.classify_tree([]), "existing")

    def test_the_mode_lands_in_the_file(self):
        answers = {("GET", repo_path(REPOSITORY, "git/trees/main?recursive=1")): (200, tree("README.md", "src/a.py")),
                   ("GET", repo_path(ORG_REPOSITORY, "git/trees/main?recursive=1")): (200, tree("README.rst", "COPYING"))}
        code, written, _, _ = self.run_sweep(FakeGitHub(answers, repositories=[REPOSITORY, ORG_REPOSITORY]))
        self.assertEqual((code, written), (0, "77\t4242\texisting\n77\t5151\tnew\n"))

    def test_a_default_branch_with_a_slash_is_one_path_segment(self):
        repo = repository(default_branch="release/1")
        github = FakeGitHub(repositories=[repo])
        code, written, _, _ = self.run_sweep(github)
        self.assertEqual((code, written), (0, "77\t4242\tnew\n"))
        self.assertIn(repo_path(repo, "branches/release%2F1"), github.paths())
        self.assertIn(repo_path(repo, "git/trees/release%2F1?recursive=1"), github.paths())

    # -- the tokens --

    def test_the_jwt_reaches_the_apps_endpoints_and_the_installation_token_the_rest(self):
        github = FakeGitHub()
        self.run_sweep(github)
        apps = [path for path in github.paths() if path == APP or path.startswith("/app/")]
        self.assertEqual(len(apps), 3)
        self.assertTrue(any(path not in apps for path in github.paths()))
        for method, path, headers, body in github.calls:
            with self.subTest(call=(method, path)):
                expected = JWT if path in apps else TOKEN
                self.assertEqual(headers["Authorization"], f"Bearer {expected}")
                self.assertEqual(headers["X-GitHub-Api-Version"], sweep.API_VERSION)
                self.assertEqual(headers["Accept"], "application/vnd.github+json")
                self.assertEqual("Content-Type" in headers, body is not None)
        self.assertIn(("POST", "/app/installations/77/access_tokens", {}),
                      [(method, path, body) for method, path, _, body in github.calls])

    def test_the_installations_token_is_revoked_after_its_repositories(self):
        github = FakeGitHub()
        self.run_sweep(github)
        paths = github.paths()
        self.assertEqual(paths[-1], "/installation/token")
        self.assertEqual(github.calls[-1][0], "DELETE")
        self.assertEqual(github.calls[-1][2]["Authorization"], f"Bearer {TOKEN}")
        self.assertLess(paths.index(REPOSITORIES), paths.index("/installation/token"))

    def test_the_token_is_revoked_even_when_the_repositories_cannot_be_listed(self):
        github = FakeGitHub({("GET", REPOSITORIES): (500, {"message": "Server Error"})})
        code, written, out, err = self.run_sweep(github)
        self.assertEqual((code, written, err), (0, "", ""))
        self.assertEqual(out, "sweep: 1 installation (1 unreadable), 0 repositories, 0 candidates, 0 skipped\n")
        self.assertEqual(github.paths("DELETE"), ["/installation/token"])

    def test_a_revocation_that_fails_costs_nothing(self):
        github = FakeGitHub({("DELETE", "/installation/token"): (500, {"message": "Server Error"})})
        code, written, out, err = self.run_sweep(github)
        self.assertEqual((code, written, err), (0, "77\t4242\tnew\n", ""))
        self.assertNotIn("Server Error", out)

    def test_an_installation_whose_token_cannot_be_made_is_passed_over(self):
        second = installation(78, "octo-org", "Organization")
        answers = {("POST", "/app/installations/77/access_tokens"): (403, {"message": "This installation has been suspended"})}
        github = FakeGitHub(answers, installations=[INSTALLATION, second])
        code, written, out, err = self.run_sweep(github)
        self.assertEqual((code, written, err), (0, "78\t4242\tnew\n", ""))
        self.assertEqual(out, "sweep: 2 installations (1 unreadable), 1 repository, 1 candidate, 0 skipped\n")
        self.assertNotIn("suspended", out)
        answers = {("POST", "/app/installations/77/access_tokens"): (201, {"expires_at": "soon"})}
        _, _, out, _ = self.run_sweep(FakeGitHub(answers))
        self.assertIn("1 installation (1 unreadable)", out)

    def test_an_installation_short_of_permissions_is_passed_over_without_a_token(self):
        """A run on its repositories would fail at the token every ten
        minutes; the owner has a permission to accept first."""
        short = installation(78, "octo-org", "Organization", {**PERMISSIONS, "workflows": "read"})
        github = FakeGitHub(installations=[INSTALLATION, short])
        code, written, out, err = self.run_sweep(github)
        self.assertEqual((code, written, err), (0, "77\t4242\tnew\n", ""))
        self.assertEqual(out, "sweep: 2 installations (1 permissions), 1 repository, 1 candidate, 0 skipped\n")
        self.assertEqual(github.paths("POST"), ["/app/installations/77/access_tokens"])
        self.assertNotIn("octo-org", out)

    def test_every_permission_the_run_asks_for_must_be_write(self):
        self.assertTrue(sweep.has_permissions(INSTALLATION))
        self.assertTrue(sweep.has_permissions(installation(permissions={**PERMISSIONS, "administration": "write"})))
        for name in ("contents", "issues", "pull_requests", "workflows"):
            with self.subTest(missing=name):
                self.assertFalse(sweep.has_permissions(installation(permissions={**PERMISSIONS, name: "read"})))
                without = {key: value for key, value in PERMISSIONS.items() if key != name}
                self.assertFalse(sweep.has_permissions(installation(permissions=without)))
        self.assertTrue(sweep.has_permissions(installation(permissions={**PERMISSIONS, "metadata": "read"})))
        self.assertFalse(sweep.has_permissions({"id": 1}))
        self.assertFalse(sweep.has_permissions({"id": 1, "permissions": None}))

    def test_the_installations_passed_over_are_counted_by_reason(self):
        short = installation(78, "octo-org", "Organization", {"metadata": "read"})
        answers = {("POST", "/app/installations/77/access_tokens"): (403, {"message": "suspended"})}
        _, written, out, _ = self.run_sweep(FakeGitHub(answers, installations=[INSTALLATION, short]))
        self.assertEqual(written, "")
        self.assertEqual(out, "sweep: 2 installations (1 permissions, 1 unreadable), 0 repositories, 0 candidates, 0 skipped\n")

    # -- the grace --

    def test_a_fresh_installation_is_left_to_the_form_without_a_token(self):
        """A person who installs the App and fills in the form within the
        grace keeps the form's choices: the sweep waits it out."""
        fresh = installation(78, "octo-org", "Organization", updated_at=moment(10 * 60))
        github = FakeGitHub(installations=[INSTALLATION, fresh])
        code, written, out, err = self.run_sweep(github)
        self.assertEqual((code, written, err), (0, "77\t4242\tnew\n", ""))
        self.assertEqual(out, "sweep: 2 installations (1 fresh), 1 repository, 1 candidate, 0 skipped\n")
        self.assertEqual(github.paths("POST"), ["/app/installations/77/access_tokens"])
        # Past the grace, by the option or by the clock, it is swept.
        code, written, out, _ = self.run_sweep(FakeGitHub(installations=[INSTALLATION, fresh]), "--grace-minutes", "5")
        self.assertEqual((code, written), (0, "77\t4242\tnew\n78\t4242\tnew\n"))
        self.assertIn("2 installations, 2 repositories", out)
        aged = installation(78, "octo-org", "Organization", updated_at=moment(30 * 60))
        code, written, _, _ = self.run_sweep(FakeGitHub(installations=[aged]))
        self.assertEqual((code, written), (0, "78\t4242\tnew\n"))
        just = installation(78, "octo-org", "Organization", updated_at=moment(30 * 60 - 1))
        _, _, out, _ = self.run_sweep(FakeGitHub(installations=[just]))
        self.assertIn("1 installation (1 fresh)", out)

    def test_the_installations_date_is_updated_at_then_created_at(self):
        """GitHub dates an installation twice; the later one is read, and
        an installation with no readable date is swept as any other."""
        fresh, old = moment(60), INSTALLED
        self.assertTrue(sweep.is_fresh(installation(updated_at=fresh, created_at=old), NOW, 1800))
        self.assertFalse(sweep.is_fresh(installation(updated_at=old, created_at=fresh), NOW, 1800))
        without = {key: value for key, value in installation(created_at=fresh).items() if key != "updated_at"}
        self.assertTrue(sweep.is_fresh(without, NOW, 1800))
        self.assertTrue(sweep.is_fresh(installation(updated_at=None, created_at=fresh), NOW, 1800))
        self.assertTrue(sweep.is_fresh(installation(updated_at="soon", created_at=fresh), NOW, 1800))
        self.assertFalse(sweep.is_fresh(installation(updated_at="soon", created_at="later"), NOW, 1800))
        self.assertFalse(sweep.is_fresh({"id": 1}, NOW, 1800))
        self.assertTrue(sweep.is_fresh(installation(updated_at="2024-10-03T23:59:00+00:00"), NOW, 1800))
        self.assertTrue(sweep.is_fresh(installation(updated_at="2024-10-03T23:59:00"), NOW, 1800))
        code, written, out, _ = self.run_sweep(FakeGitHub(installations=[{**INSTALLATION, "updated_at": 7, "created_at": None}]))
        self.assertEqual((code, written), (0, "77\t4242\tnew\n"))
        self.assertIn("1 installation, 1 repository", out)

    def test_permissions_are_read_before_the_date(self):
        short = installation(78, "octo-org", "Organization", {"metadata": "read"}, updated_at=moment(60))
        _, _, out, _ = self.run_sweep(FakeGitHub(installations=[short]))
        self.assertIn("1 installation (1 permissions)", out)

    # -- the budget and the rotation --

    def test_the_budget_takes_up_no_new_installation_once_spent(self):
        """Each call takes a minute: the App's two reads, then one
        installation's token, list, seven checks and revocation take the
        clock past 420 seconds, and the other two are deferred. What was
        found is in the file and the exit is 0."""
        installations = [INSTALLATION, installation(78, "octo-org", "Organization"), installation(79, "hubot")]
        github = FakeGitHub(installations=installations, seconds_per_call=60)
        code, written, out, err = self.run_sweep(github)
        self.assertEqual((code, written, err), (0, "77\t4242\tnew\n", ""))
        self.assertEqual(out, "sweep: 3 installations (2 deferred), 1 repository, 1 candidate, 0 skipped, "
                              "cut short by the budget\n")
        self.assertEqual(github.paths("POST"), ["/app/installations/77/access_tokens"])
        self.assertEqual(github.paths("DELETE"), ["/installation/token"])
        for name in NAMES:
            self.assertNotIn(name, out)

    def test_the_budget_takes_up_no_new_repository_once_spent(self):
        """An installation cut short among its repositories is deferred
        too, with the candidates found in it kept; its token is revoked."""
        github = FakeGitHub(repositories=[REPOSITORY, ORG_REPOSITORY], seconds_per_call=60)
        code, written, out, err = self.run_sweep(github)
        self.assertEqual((code, written, err), (0, "77\t4242\tnew\n", ""))
        self.assertEqual(out, "sweep: 1 installation (1 deferred), 1 repository, 1 candidate, 0 skipped, "
                              "cut short by the budget\n")
        self.assertEqual(github.paths()[-1], "/installation/token")
        self.assertFalse(any("octo-org" in path for path in github.paths()))

    def test_the_budget_is_the_option_and_counts_from_the_start(self):
        installations = [INSTALLATION, installation(78, "octo-org", "Organization")]
        github = FakeGitHub(installations=installations, seconds_per_call=60)
        code, written, out, _ = self.run_sweep(github, "--budget-seconds", "100000")
        self.assertEqual((code, written), (0, "77\t4242\tnew\n78\t4242\tnew\n"))
        self.assertEqual(out, "sweep: 2 installations, 2 repositories, 2 candidates, 0 skipped\n")
        # The App's own two reads spend the budget before any installation.
        github = FakeGitHub(installations=installations, seconds_per_call=60)
        code, written, out, _ = self.run_sweep(github, "--budget-seconds", "90")
        self.assertEqual((code, written), (0, ""))
        self.assertEqual(out, "sweep: 2 installations (2 deferred), 0 repositories, 0 candidates, 0 skipped, "
                              "cut short by the budget\n")
        self.assertEqual(github.paths("POST"), [])

    def test_a_deferred_installation_counts_with_the_other_reasons(self):
        short = installation(78, "octo-org", "Organization", {"metadata": "read"})
        github = FakeGitHub(installations=[short, INSTALLATION, installation(79, "hubot")], seconds_per_call=60)
        _, written, out, _ = self.run_sweep(github)
        self.assertEqual(written, "77\t4242\tnew\n")
        self.assertEqual(out, "sweep: 3 installations (1 deferred, 1 permissions), 1 repository, 1 candidate, 0 skipped, "
                              "cut short by the budget\n")

    def test_the_starting_installation_moves_along_every_ten_minutes(self):
        """One installation too large for a budget would otherwise be
        swept first, and alone, every time; the repositories inside one
        keep their order."""
        installations = [INSTALLATION, installation(78, "octo-org", "Organization"), installation(79, "hubot")]
        turns = ((0, [77, 78, 79]), (9, [77, 78, 79]), (10, [78, 79, 77]), (20, [79, 77, 78]), (30, [77, 78, 79]))
        for minutes, order in turns:
            with self.subTest(minutes=minutes):
                github = FakeGitHub(installations=installations, start=NOW + minutes * 60)
                code, written, _, _ = self.run_sweep(github)
                self.assertEqual(code, 0)
                self.assertEqual(written, "".join(f"{number}\t4242\tnew\n" for number in order))
                self.assertEqual(github.paths("POST"), [f"/app/installations/{number}/access_tokens" for number in order])
        self.assertEqual(sweep.rotated([], NOW), [])
        self.assertEqual(sweep.rotated([1], NOW + 600), [1])

    # -- pagination --

    def test_installations_are_read_page_after_page_as_the_link_header_points(self):
        second = installation(78, "octo-org", "Organization")
        page_two = f"{INSTALLATIONS}&page=2"
        link = f'<{sweep.API}{page_two}>; rel="next", <{sweep.API}{page_two}>; rel="last"'
        answers = {("GET", INSTALLATIONS): (200, [INSTALLATION], link),
                   ("GET", page_two): (200, [second], f'<{sweep.API}{INSTALLATIONS}>; rel="prev"')}
        github = FakeGitHub(answers)
        code, written, out, _ = self.run_sweep(github)
        self.assertEqual((code, written), (0, "77\t4242\tnew\n78\t4242\tnew\n"))
        self.assertIn("2 installations, 2 repositories", out)
        self.assertEqual(github.paths().count(page_two), 1)
        self.assertEqual(github.paths("POST"), ["/app/installations/77/access_tokens", "/app/installations/78/access_tokens"])

    def test_repositories_are_read_page_after_page(self):
        page_two = f"{REPOSITORIES}&page=2"
        answers = {("GET", REPOSITORIES): (200, {"total_count": 2, "repositories": [REPOSITORY]},
                                           f'<{sweep.API}{page_two}>; rel="next"'),
                   ("GET", page_two): (200, {"total_count": 2, "repositories": [ORG_REPOSITORY]})}
        code, written, out, _ = self.run_sweep(FakeGitHub(answers))
        self.assertEqual((code, written), (0, "77\t4242\tnew\n77\t5151\tnew\n"))
        self.assertIn("1 installation, 2 repositories, 2 candidates", out)

    def test_a_next_page_outside_the_api_is_not_followed(self):
        answers = {("GET", INSTALLATIONS): (200, [INSTALLATION], '<https://elsewhere.example/x>; rel="next"')}
        github = FakeGitHub(answers)
        code, _, out, _ = self.run_sweep(github)
        self.assertEqual(code, 0)
        self.assertIn("1 installation,", out)
        self.assertFalse(any("elsewhere" in path for path in github.paths()))

    def test_the_link_parser(self):
        link = ('<https://api.github.com/app/installations?per_page=100&page=2>; rel="next", '
                '<https://api.github.com/app/installations?per_page=100&page=5>; rel="last"')
        self.assertEqual(sweep.next_page(link), "https://api.github.com/app/installations?per_page=100&page=2")
        self.assertIsNone(sweep.next_page('<https://api.github.com/a?page=1>; rel="prev"'))
        self.assertIsNone(sweep.next_page(""))
        self.assertIsNone(sweep.next_page(None))

    # -- the output and the failures --

    def test_each_candidate_is_written_as_it_is_found_in_the_order_found(self):
        """The file is in the order of discovery, not sorted, and each line
        is on disk before the next installation's token is minted, so a
        run cut short has what it found."""
        second = installation(70, "octo-org", "Organization")
        early, late = repository("octo-org/a", 300), repository("octo-org/b", 200)
        out, on_disk = self.out, []

        class Github(FakeGitHub):
            def __call__(self, method, url, headers, body):
                if method == "POST" and "/app/installations/70/" in url:
                    on_disk.append(out.read_text(encoding="utf-8"))
                return super().__call__(method, url, headers, body)

        github = Github(repositories=[early, late], installations=[INSTALLATION, second])
        code, written, _, _ = self.run_sweep(github)
        self.assertEqual(code, 0)
        self.assertEqual(written, "77\t300\tnew\n77\t200\tnew\n70\t300\tnew\n70\t200\tnew\n")
        self.assertEqual(on_disk, ["77\t300\tnew\n77\t200\tnew\n"])

    def test_a_jwt_github_refuses_exits_1_with_one_line_and_no_file(self):
        github = FakeGitHub({("GET", INSTALLATIONS): (401, {"message": "A JSON web token could not be decoded"})})
        code, written, out, err = self.run_sweep(github)
        self.assertEqual((code, written, out), (1, None, ""))
        self.assertEqual(err, "sweep: the installations could not be listed (HTTP 401: A JSON web token could not be decoded)\n")
        self.assertNotIn(JWT, err)

    def test_an_app_record_that_cannot_be_read_exits_1_with_one_line_and_no_file(self):
        """Without the App's slug the refused check cannot be made, so
        nothing is swept, as when the installations cannot be listed."""
        github = FakeGitHub({("GET", APP): (401, {"message": "Bad credentials"})})
        code, written, out, err = self.run_sweep(github)
        self.assertEqual((code, written, out), (1, None, ""))
        self.assertEqual(err, "sweep: the App could not be read (HTTP 401: Bad credentials)\n")
        self.assertEqual(github.paths(), [APP])
        for answer in ({"id": 1}, {"slug": ""}, {"slug": 5}, [], "x"):
            with self.subTest(answer=answer):
                code, written, _, err = self.run_sweep(FakeGitHub({("GET", APP): (200, answer)}))
                self.assertEqual((code, written), (1, None))
                self.assertEqual(err, "sweep: the App could not be read (GitHub's answer held no slug)\n")

    def test_a_second_page_that_fails_leaves_no_file(self):
        page_two = f"{INSTALLATIONS}&page=2"
        answers = {("GET", INSTALLATIONS): (200, [INSTALLATION], f'<{sweep.API}{page_two}>; rel="next"'),
                   ("GET", page_two): (502, {"message": "Bad Gateway"})}
        code, written, out, err = self.run_sweep(FakeGitHub(answers))
        self.assertEqual((code, written, out), (1, None, ""))
        self.assertEqual(err.count("\n"), 1)
        self.assertIn("HTTP 502: Bad Gateway", err)

    def test_github_out_of_reach_is_the_same_failure(self):
        code, written, _, err = self.run_sweep(FakeGitHub(raising="GitHub could not be reached (URLError)"))
        self.assertEqual((code, written), (1, None))
        self.assertEqual(err, "sweep: the App could not be read (GitHub could not be reached (URLError))\n")

    def test_an_answer_that_is_not_a_list_is_a_failure(self):
        code, _, _, err = self.run_sweep(FakeGitHub({("GET", INSTALLATIONS): (200, {"message": "odd"})}))
        self.assertEqual(code, 1)
        self.assertIn("was not a list", err)

    def test_no_jwt_is_an_error_and_writes_no_file(self):
        with mock.patch.dict(os.environ, {"APP_JWT": ""}):
            code, written, _, err = self.run_sweep(FakeGitHub())
        self.assertEqual((code, written), (2, None))
        self.assertIn("APP_JWT", err)

    def test_a_file_that_cannot_be_written_is_an_error_before_any_token(self):
        self.out = Path(self.scratch.name) / "missing" / "candidates.tsv"
        github = FakeGitHub()
        code, written, out, err = self.run_sweep(github)
        self.assertEqual((code, written, out), (1, None, ""))
        self.assertTrue(err.startswith("sweep: "))
        self.assertEqual(github.paths("POST"), [])


class Transport(unittest.TestCase):
    def test_the_reply_carries_its_headers(self):
        class Reply:
            status = 200
            headers = {"Link": '<https://api.github.com/x?page=2>; rel="next"', "Content-Type": "application/json"}

            def read(self):
                return b"[]"

            def __enter__(self):
                return self

            def __exit__(self, *ignored):
                return False

        with mock.patch.object(sweep.OPENER, "open", lambda request, timeout: Reply()):
            status, headers, data = sweep.urllib_transport("GET", "https://api.github.com/x", {}, None)
        self.assertEqual((status, data), (200, b"[]"))
        self.assertEqual(sweep.next_page(headers["Link"]), "https://api.github.com/x?page=2")

    def test_a_refusal_is_an_answer_with_its_headers(self):
        import urllib.error

        def opening(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {"X-Why": "gone"}, io.BytesIO(b'{"message": "Not Found"}'))

        with mock.patch.object(sweep.OPENER, "open", opening):
            status, headers, data = sweep.urllib_transport("GET", "https://api.github.com/x", {}, None)
        self.assertEqual((status, data), (404, b'{"message": "Not Found"}'))
        self.assertEqual(headers.get("X-Why"), "gone")

    def test_a_body_cut_short_is_a_failure_to_get_an_answer(self):
        import http.client

        def opening(request, timeout):
            raise http.client.IncompleteRead(b"partial")

        with mock.patch.object(sweep.OPENER, "open", opening):
            with self.assertRaises(sweep.GitHubError) as caught:
                sweep.urllib_transport("GET", "https://api.github.com/x", {}, None)
        self.assertIn("IncompleteRead", str(caught.exception))
        self.assertIsNone(caught.exception.status)

    def test_a_redirect_is_handed_back_as_it_is(self):
        self.assertIsNone(sweep.NoRedirect().redirect_request(None, None, 301, "", {}, "https://elsewhere.example"))
        self.assertTrue(any(isinstance(handler, sweep.NoRedirect) for handler in sweep.OPENER.handlers))

    def test_a_refusal_keeps_its_status_and_githubs_words(self):
        def transport(method, url, headers, body):
            return 422, {}, json.dumps({"message": "Validation Failed", "errors": [{"code": "x"}]}).encode("utf-8")

        with self.assertRaises(sweep.GitHubError) as caught:
            sweep.GitHub("t", transport).call("GET", "/x")
        self.assertEqual((str(caught.exception), caught.exception.status), ("HTTP 422: Validation Failed x", 422))
        self.assertEqual(sweep.github_message(b"not json"), "")
        self.assertEqual(sweep.github_message(b"[1]"), "")

    def test_an_answer_that_is_not_json_is_a_refusal(self):
        def transport(method, url, headers, body):
            return 200, {}, b"<html>ok, says a proxy</html>"

        with self.assertRaises(sweep.GitHubError) as caught:
            sweep.GitHub("t", transport).call("GET", "/x")
        self.assertEqual(str(caught.exception), "HTTP 200: GitHub's answer was not JSON")

    def test_a_header_is_found_whatever_its_case(self):
        def transport(method, url, headers, body):
            return 200, {"LINK": '<https://api.github.com/x?page=2>; rel="next"'}, b"[]"

        _, headers = sweep.GitHub("t", transport).request("GET", "https://api.github.com/x")
        self.assertEqual(headers["link"], '<https://api.github.com/x?page=2>; rel="next"')


if __name__ == "__main__":
    unittest.main()
