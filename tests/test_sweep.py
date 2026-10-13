"""scripts/sweep.py is the GitHub client and the adoption rules the form's
paths share, now that the sweep itself is gone.

The client sends one token's headers and reads pages as the Link header
points; a refusal keeps GitHub's status and words. The rules say which of
an installation's repositories have no adoption yet, asked by id so the
form's workflow never learns a name, and which kind a tree reads as. A
check that answers neither yes nor a clean 404 is the caller's to answer,
never a guess.
"""

import io
import json
import unittest
from pathlib import Path
from unittest import mock
import sys

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))

import sweep  # noqa: E402

TOKEN = "ghs_installation_token_for_tests"
NOT_FOUND = (404, {"message": "Not Found"})
IS_EMPTY = (409, {"message": "Git Repository is empty."})


def repository(full_name="mona/widget", number=4242, owner_type="User", **more):
    owner = full_name.split("/")[0]
    fields = {"id": number, "full_name": full_name, "owner": {"login": owner, "type": owner_type},
              "default_branch": "main", "archived": False, "fork": False, "private": False}
    fields.update(more)
    return fields


REPOSITORY = repository()


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


class FakeGitHub:
    """A transport that answers from a table keyed (method, path) and keeps
    every call; by default it knows a repository whose default branch is
    there, with no branch symphony/adopt, no file asked about and a tree
    holding one README. An entry is (status, answer) or (status, answer,
    Link header)."""

    def __init__(self, answers=None, raising=None):
        self.answers = dict(answers or {})
        self.raising = raising
        self.calls = []

    def __call__(self, method, url, headers, body):
        path = url.removeprefix(sweep.API)
        self.calls.append((method, path, headers, body))
        if self.raising:
            raise sweep.GitHubError(self.raising)
        status, answer, *link = self.answers.get((method, path)) or self.default(method, path)
        replied = {"Link": link[0]} if link else {}
        return status, replied, b"" if answer is None else json.dumps(answer).encode("utf-8")

    def default(self, method, path):
        if (method, path) == ("DELETE", "/installation/token"):
            return 204, None
        if "/branches/" in path:
            return 200, {"name": "main"}
        if "/git/matching-refs/heads/" in path:
            return 200, []
        if "/contents/" in path:
            return NOT_FOUND
        if "/git/trees/" in path:
            return 200, tree("README.md")
        return NOT_FOUND

    def paths(self, method=None):
        return [path for called, path, _, _ in self.calls if method in (None, called)]


def client(answers=None, raising=None):
    github = FakeGitHub(answers, raising)
    return sweep.GitHub(TOKEN, github), github


class TheRules(unittest.TestCase):
    def test_the_unadopted_among_an_installations_repositories_asked_by_id(self):
        """The form's workflow holds ids and must not learn a name: with
        by_id the checks go to /repositories/ID, and unadopted keeps the
        repositories with a commit and no offer, adoption or opt-out, and
        the empty ones, with no branch at all however GitHub says so, whose
        first commit the form's run makes; a default branch missing beside
        branches of the repository's own is no empty repository."""
        self.assertEqual(sweep.repo_path(REPOSITORY), "/repos/mona/widget")
        self.assertEqual(sweep.repo_path(dict(REPOSITORY, by_id=True)), "/repositories/4242")
        offered = dict(repository("mona/offered", 7), by_id=True)
        adopted = dict(repository("mona/adopted", 8), by_id=True)
        empty = dict(repository("mona/empty", 9), by_id=True)
        stray = dict(repository("mona/stray", 10), by_id=True)
        blank = dict(repository("mona/blank", 11), by_id=True)
        free = dict(REPOSITORY, by_id=True)
        github, calls = client({
            ("GET", "/repositories/7/git/matching-refs/heads/symphony/adopt"): (200, [{"ref": "refs/heads/symphony/adopt"}]),
            ("GET", "/repositories/8/contents/docs/agents/PROTOCOL.md"): (200, {"type": "file"}),
            ("GET", "/repositories/9/branches/main"): NOT_FOUND,
            ("GET", "/repositories/9/branches?per_page=1"): (200, []),
            ("GET", "/repositories/10/branches/main"): NOT_FOUND,
            ("GET", "/repositories/10/branches?per_page=1"): (200, [{"name": "draft"}]),
            ("GET", "/repositories/11/branches/main"): IS_EMPTY,
            ("GET", "/repositories/11/branches?per_page=1"): IS_EMPTY,
        })
        chosen = sweep.unadopted(github, [offered, adopted, empty, free, dict(free, archived=True), stray, blank])
        self.assertEqual([item["id"] for item in chosen], [9, 4242, 11])
        self.assertTrue(calls.paths())
        self.assertTrue(all(path.startswith("/repositories/") for path in calls.paths()))
        # An empty repository holds no branch and no file to ask about.
        for number in (9, 11):
            self.assertEqual([path for path in calls.paths() if path.startswith(f"/repositories/{number}/")],
                             [f"/repositories/{number}/branches/main", f"/repositories/{number}/branches?per_page=1"])
        # Any other refusal of the list is the caller's to answer.
        failing, _ = client({("GET", "/repositories/9/branches/main"): NOT_FOUND,
                             ("GET", "/repositories/9/branches?per_page=1"): (500, {"message": "boom"})})
        with self.assertRaises(sweep.GitHubError):
            sweep.unadopted(failing, [empty])
        # A check that fails is the caller's to answer, as a refusal.
        unreachable, _ = client(raising="GitHub could not be reached")
        with self.assertRaises(sweep.GitHubError):
            sweep.unadopted(unreachable, [free])

    def test_the_newest_repository_comes_first_for_the_caller_that_sorts(self):
        older = repository("mona/older", 1, created_at="2026-01-01T00:00:00Z")
        newer = repository("mona/newer", 2, created_at="2026-10-11T04:00:00Z")
        naive = repository("mona/naive", 4, created_at="2026-10-11T03:00:00")
        undated = repository("mona/undated", 3)
        chosen = sorted([older, newer, undated, naive], key=sweep.created_at, reverse=True)
        self.assertEqual([r["id"] for r in chosen], [2, 4, 1, 3])
        self.assertEqual(sweep.created_at(repository(created_at="soon")), 0.0)
        self.assertEqual(sweep.created_at(repository(created_at=7)), 0.0)

    def test_a_commit_is_the_default_branch_being_there(self):
        github, _ = client()
        self.assertTrue(sweep.has_commit(github, REPOSITORY))
        for answer in (NOT_FOUND, IS_EMPTY):
            with self.subTest(answer=answer):
                github, _ = client({("GET", repo_path(REPOSITORY, "branches/main")): answer})
                self.assertFalse(sweep.has_commit(github, REPOSITORY))
        github, _ = client({("GET", repo_path(REPOSITORY, "branches/main")): (403, {"message": "no"})})
        with self.assertRaises(sweep.GitHubError):
            sweep.has_commit(github, REPOSITORY)

    def test_an_empty_repository_has_no_branch_at_all(self):
        for answer, empty in (((200, []), True), (IS_EMPTY, True), ((200, [{"name": "draft"}]), False)):
            with self.subTest(answer=answer):
                github, _ = client({("GET", repo_path(REPOSITORY, "branches?per_page=1")): answer})
                self.assertEqual(sweep.is_empty(github, REPOSITORY), empty)
        github, _ = client({("GET", repo_path(REPOSITORY, "branches?per_page=1")): (200, {"message": "odd"})})
        with self.assertRaises(sweep.GitHubError):
            sweep.is_empty(github, REPOSITORY)

    def test_the_branch_symphony_adopt_is_matched_exactly_under_either_name(self):
        matching = ("GET", repo_path(REPOSITORY, "git/matching-refs/heads/symphony/adopt"))
        exact = {matching: (200, [{"ref": "refs/heads/symphony/adopt-again"}, {"ref": "refs/heads/symphony/adopt"}])}
        github, _ = client(exact)
        self.assertTrue(sweep.has_adopt_branch(github, REPOSITORY))
        github, calls = client({matching: (200, [{"ref": "refs/heads/symphony/adopt-again"}])})
        self.assertFalse(sweep.has_adopt_branch(github, REPOSITORY))
        self.assertIn(repo_path(REPOSITORY, "git/matching-refs/heads/sdlc/adopt"), calls.paths())
        old = {("GET", repo_path(REPOSITORY, "git/matching-refs/heads/sdlc/adopt")): (200, [{"ref": "refs/heads/sdlc/adopt"}])}
        github, _ = client(old)
        self.assertTrue(sweep.has_adopt_branch(github, REPOSITORY))
        github, _ = client({matching: (200, {"message": "odd"})})
        with self.assertRaises(sweep.GitHubError):
            sweep.has_adopt_branch(github, REPOSITORY)

    def test_an_adoption_is_the_protocols_text_on_the_default_branch(self):
        protocol = ("GET", repo_path(REPOSITORY, "contents/docs/agents/PROTOCOL.md"))
        github, _ = client({protocol: (200, {"name": "PROTOCOL.md"})})
        self.assertTrue(sweep.is_adopted(github, REPOSITORY))
        github, _ = client()
        self.assertFalse(sweep.is_adopted(github, REPOSITORY))
        github, _ = client({protocol: (403, {"message": "Resource not accessible by integration"})})
        with self.assertRaises(sweep.GitHubError):
            sweep.is_adopted(github, REPOSITORY)

    def switch(self, content, encoding="base64", path=".github/symphony-adopt"):
        return {("GET", repo_path(REPOSITORY, f"contents/{path}")):
                (200, {"name": path.rsplit("/", 1)[-1], "encoding": encoding, "content": content})}

    def test_a_switch_that_says_off_is_an_opt_out_under_either_name(self):
        # GitHub wraps the base64 in newlines, the word may be any case,
        # and an editor may have put a byte order mark before it.
        for content in ("b2Zm", "T0ZG\n", "ICBvZmYgIAo=\n", "77u/b2ZmCg=="):
            with self.subTest(content=content):
                github, _ = client(self.switch(content))
                self.assertTrue(sweep.opted_out(github, REPOSITORY))
        github, _ = client(self.switch("b2Zm", path=".github/sdlc-adopt"))
        self.assertTrue(sweep.opted_out(github, REPOSITORY))

    def test_a_switch_that_does_not_say_off_is_not_an_opt_out(self):
        for answers in (self.switch("b24="), self.switch("", "none"), self.switch("/w=="), None,
                        {("GET", repo_path(REPOSITORY, "contents/.github/symphony-adopt")): (200, [{"name": "a"}])}):
            with self.subTest(answers=answers):
                github, _ = client(answers)
                self.assertFalse(sweep.opted_out(github, REPOSITORY))
        github, _ = client({("GET", repo_path(REPOSITORY, "contents/.github/symphony-adopt")): (500, {"message": "x"})})
        with self.assertRaises(sweep.GitHubError):
            sweep.opted_out(github, REPOSITORY)

    def test_a_default_branch_with_a_slash_is_one_path_segment(self):
        repo = repository(default_branch="release/1")
        github, calls = client()
        self.assertTrue(sweep.has_commit(github, repo))
        self.assertEqual(calls.paths(), [repo_path(repo, "branches/release%2F1")])

    # -- the kind --

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


class TheClient(unittest.TestCase):
    def test_every_call_carries_the_tokens_headers(self):
        github, calls = client({("POST", "/app/installations/77/access_tokens"): (201, {"token": "t"})})
        github.call("GET", "/repos/mona/widget/branches/main")
        github.call("POST", "/app/installations/77/access_tokens", {})
        for method, path, headers, body in calls.calls:
            with self.subTest(call=(method, path)):
                self.assertEqual(headers["Authorization"], f"Bearer {TOKEN}")
                self.assertEqual(headers["X-GitHub-Api-Version"], sweep.API_VERSION)
                self.assertEqual(headers["Accept"], "application/vnd.github+json")
                self.assertEqual("Content-Type" in headers, body is not None)
        self.assertEqual(github.with_token("other").token, "other")
        self.assertIs(github.with_token("other").transport, calls)

    def test_a_list_is_read_page_after_page_as_the_link_header_points(self):
        first, second = "/installation/repositories?per_page=100", "/installation/repositories?per_page=100&page=2"
        answers = {("GET", first): (200, {"total_count": 2, "repositories": [REPOSITORY]},
                                    f'<{sweep.API}{second}>; rel="next", <{sweep.API}{second}>; rel="last"'),
                   ("GET", second): (200, {"total_count": 2, "repositories": [repository("mona/gadget", 5)]},
                                     f'<{sweep.API}{first}>; rel="prev"')}
        github, calls = client(answers)
        self.assertEqual([r["id"] for r in github.pages(first, key="repositories")], [4242, 5])
        self.assertEqual(calls.paths(), [first, second])

    def test_a_next_page_outside_the_api_is_not_followed_and_a_page_seen_twice_ends_the_walk(self):
        path = "/app/installations?per_page=100"
        github, calls = client({("GET", path): (200, [{"id": 77}], '<https://elsewhere.example/x>; rel="next"')})
        self.assertEqual(list(github.pages(path)), [{"id": 77}])
        self.assertEqual(calls.paths(), [path])
        github, calls = client({("GET", path): (200, [{"id": 77}], f'<{sweep.API}{path}>; rel="next"')})
        self.assertEqual(list(github.pages(path)), [{"id": 77}])
        self.assertEqual(calls.paths(), [path])

    def test_an_answer_that_is_not_a_list_is_a_refusal(self):
        github, _ = client({("GET", "/x"): (200, {"message": "odd"})})
        with self.assertRaises(sweep.GitHubError):
            github.listed("/x")
        with self.assertRaises(sweep.GitHubError):
            list(github.pages("/x"))
        github, _ = client({("GET", "/x"): (200, {"items": [1]})})
        self.assertEqual(list(github.pages("/x", key="items")), [1])

    def test_the_link_parser(self):
        link = ('<https://api.github.com/app/installations?per_page=100&page=2>; rel="next", '
                '<https://api.github.com/app/installations?per_page=100&page=5>; rel="last"')
        self.assertEqual(sweep.next_page(link), "https://api.github.com/app/installations?per_page=100&page=2")
        self.assertIsNone(sweep.next_page('<https://api.github.com/a?page=1>; rel="prev"'))
        self.assertIsNone(sweep.next_page(""))
        self.assertIsNone(sweep.next_page(None))

    def test_a_revocation_that_fails_costs_nothing(self):
        github, calls = client({("DELETE", "/installation/token"): (500, {"message": "Server Error"})})
        sweep.revoke(github)
        self.assertEqual(calls.paths("DELETE"), ["/installation/token"])
        sweep.revoke(client(raising="GitHub could not be reached (URLError)")[0])


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
