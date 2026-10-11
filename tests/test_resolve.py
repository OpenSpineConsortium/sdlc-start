"""resolve.py turns the number a form carried into the repositories to
adopt, by id, for either App's installation, and answers nothing alike."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import resolve  # noqa: E402
import sweep  # noqa: E402

NOT_FOUND = (404, {"message": "Not Found"})


def repository(number, name, created="2026-10-11T04:00:00Z", **more):
    fields = {"id": number, "full_name": f"mona/{name}", "owner": {"login": "mona", "type": "User"},
              "default_branch": "main", "archived": False, "created_at": created}
    fields.update(more)
    return fields


FREE = repository(1, "free")
OLDER = repository(2, "older", created="2026-01-01T00:00:00Z")
ADOPTED = repository(3, "adopted")
MAIN = {"id": 70, "account": {"id": 500, "login": "mona"}, "repository_selection": "selected"}
SETUP = {"id": 90, "account": {"id": 500, "login": "mona"}, "repository_selection": "selected"}


class Transport:
    """(status, body) by (token, method, path); the main App's JWT is
    'app', the Setup App's 'setup', the minted tokens name their
    installation."""

    def __init__(self, answers=None, repositories=(FREE, OLDER, ADOPTED), permissions=None):
        self.answers = dict(answers or {})
        self.repositories = list(repositories)
        self.permissions = {1: "admin", 2: "admin", 3: "admin"} if permissions is None else permissions
        self.calls = []

    def __call__(self, method, url, headers, body):
        token = headers["Authorization"].removeprefix("Bearer ")
        path = url.removeprefix(sweep.API)
        self.calls.append((token, method, path))
        status, answer = self.answers.get((token, method, path)) or self.default(token, method, path)
        return status, {}, json.dumps(answer).encode("utf-8") if answer is not None else b""

    def default(self, token, method, path):
        if path == "/app":
            return 200, {"id": 1, "slug": "symphonyboard"}
        if token == "app" and path == "/app/installations/70":
            return 200, MAIN
        if token == "setup" and path == "/app/installations/90":
            return 200, SETUP
        if token == "app" and path.startswith("/app/installations?"):
            return 200, [MAIN]
        if method == "POST" and path.startswith("/app/installations/") and path.endswith("/access_tokens"):
            return 201, {"token": f"token-{token}-{path.split('/')[3]}"}
        if path.startswith("/installation/repositories"):
            if token == "token-setup-90":
                return 200, {"total_count": 1, "repositories": [FREE]}
            return 200, {"total_count": len(self.repositories), "repositories": self.repositories}
        if (method, path) == ("DELETE", "/installation/token"):
            return 204, None
        if "/branches/" in path:
            return 200, {"name": "main"}
        if "/git/matching-refs/heads/" in path:
            return 200, []
        if path == "/repositories/3/contents/docs/agents/PROTOCOL.md":
            return 200, {"type": "file"}
        if "/contents/" in path:
            return NOT_FOUND
        if "/collaborators/" in path:
            number = int(path.split("/")[2])
            return 200, {"permission": self.permissions.get(number, "none")}
        return NOT_FOUND


class Resolving(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.out = Path(self.scratch.name) / "resolved"

    def run_resolve(self, transport, installation="70", author="mona", setup=True):
        env = {"APP_JWT": "app", "SETUP_JWT": "setup" if setup else ""}
        self.out.unlink(missing_ok=True)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = resolve.main(["--installation", installation, "--author", author, "--out", str(self.out)], transport)
        written = self.out.read_text(encoding="utf-8") if self.out.exists() else None
        return code, written, out.getvalue(), err.getvalue()

    def test_the_apps_own_installation_gives_every_unadopted_repository_newest_first(self):
        transport = Transport()
        code, written, out, err = self.run_resolve(transport)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(written, "installation_id=70\nrepository_ids=[1, 2]\ncount=2\n")
        self.assertEqual(out, "the installation reaches 2 repositories to adopt\n")
        # Everything by id: no path carries a name, and the token is revoked.
        self.assertFalse([path for _, _, path in transport.calls if "/repos/" in path])
        self.assertIn(("token-app-70", "DELETE", "/installation/token"), transport.calls)

    def test_only_what_the_author_administers(self):
        transport = Transport(permissions={1: "write", 2: "admin"})
        code, written, _, _ = self.run_resolve(transport)
        self.assertEqual((code, written), (0, "installation_id=70\nrepository_ids=[2]\ncount=1\n"))
        code, written, out, err = self.run_resolve(Transport(permissions={}), author="stranger")
        self.assertEqual((code, written, out, err), (3, None, "", ""))

    def test_the_setup_apps_installation_stands_for_the_apps_on_the_same_account(self):
        """The Setup App sends the person to the form too; its number finds
        the App's installation on the account and narrows the repositories
        to the ones the Setup App was given."""
        transport = Transport()
        code, written, _, _ = self.run_resolve(transport, installation="90")
        self.assertEqual((code, written), (0, "installation_id=70\nrepository_ids=[1]\ncount=1\n"))
        self.assertIn(("setup", "GET", "/app/installations/90"), transport.calls)
        self.assertIn(("token-setup-90", "DELETE", "/installation/token"), transport.calls)
        # Without the Setup App's JWT, or with a number neither App knows, nothing.
        self.assertEqual(self.run_resolve(Transport(), installation="90", setup=False)[0], 3)
        self.assertEqual(self.run_resolve(Transport(), installation="12345")[0], 3)
        # The App not installed on the Setup App's account: nothing.
        transport = Transport({("app", "GET", "/app/installations?per_page=100"): (200, [])})
        self.assertEqual(self.run_resolve(transport, installation="90")[0], 3)

    def test_nothing_to_adopt_is_three_and_a_broken_app_is_four(self):
        self.assertEqual(self.run_resolve(Transport(repositories=[ADOPTED]))[0], 3)
        code, written, out, err = self.run_resolve(Transport({("app", "GET", "/app"): (401, {"message": "bad"})}))
        self.assertEqual((code, written, out), (4, None, ""))
        self.assertTrue(err.startswith("resolve: the App could not be read"))

    def test_a_number_that_is_not_one_and_a_missing_jwt(self):
        self.assertEqual(self.run_resolve(Transport(), installation="7x")[0], 2)
        with mock.patch.dict(os.environ, {"APP_JWT": ""}):
            code = resolve.main(["--installation", "70", "--author", "mona", "--out", str(self.out)], Transport())
        self.assertEqual(code, 2)

    def test_github_failing_mid_way_is_one_and_names_nothing(self):
        transport = Transport({("token-app-70", "GET", "/repositories/1/branches/main"): (500, {"message": "boom"})})
        code, written, out, err = self.run_resolve(transport)
        self.assertEqual((code, written, out), (1, None, ""))
        self.assertNotIn("mona", err)


if __name__ == "__main__":
    unittest.main()
