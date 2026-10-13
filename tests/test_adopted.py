"""A repository adopted already is refused on every path, the named one too.

The sweep and the installation's path of the form pass over a repository
whose default branch holds docs/agents/PROTOCOL.md (scripts/sweep.py), and
a name typed on the form reaches the run by neither, so the run asks
scripts/adopted.py, which asks sweep.is_adopted itself, before it reads the
kind or stages a file. The script's answer must be the sweep's, read with
the repository's own token, and nothing it prints may name the repository,
since the run's log is public. The step of .github/workflows/adopt-run.yml
that asks it is run here for real, with gh answered from a table and the
script asking a fake GitHub: an adopted repository gets one answer that
names nothing of it and says what to do instead, and nothing after it is
read. On the form's paths the Setup App that request needed uninstalls
itself afterwards, by the step that does so after an adoption, run here
with curl answered from a table; and the stage step answers apply's
refusal of an adoption that could not write docs/agents/PROTOCOL.md, the
file the rule reads, as a refusal on the request. A named repository
without the Setup App is asked the same question by adopt.yml before it is
sent to install that App, and gets the same answer, kept in the script;
and a form from the install, which adopt.yml answers once after the run,
is answered by nothing more once the run refused it and closed its issue.
Those steps are run here for real too.
"""

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import adopted  # noqa: E402
import sweep  # noqa: E402

TOKEN = "ghs_repository_token_for_tests"
OWNER, NAME = "mona", "widget"
REPOSITORY = f"{OWNER}/{NAME}"
PROTOCOL = f"/repos/{REPOSITORY}/contents/docs/agents/PROTOCOL.md"
RUN = ROOT / ".github/workflows/adopt-run.yml"
ADOPT = ROOT / ".github/workflows/adopt.yml"
TARGET_STEP = "name: Read the repository, and stop when it cannot take the pull request"
TELL_STEP = "name: Tell the repository when the sweep's adoption was refused or failed"
ANSWER = "Nothing was done: the repository is adopted already."


class FakeGitHub:
    """Answers the contents call for docs/agents/PROTOCOL.md with the
    status given, every other call with 404, and keeps every call."""

    def __init__(self, status=404, raising=None):
        self.status = status
        self.raising = raising
        self.calls = []

    def __call__(self, method, url, headers, body):
        path = url.removeprefix(sweep.API)
        self.calls.append((method, path, headers))
        if self.raising:
            raise sweep.GitHubError(self.raising)
        if path == PROTOCOL and self.status == 200:
            return 200, {}, json.dumps({"type": "file", "name": "PROTOCOL.md"}).encode("utf-8")
        status = self.status if path == PROTOCOL else 404
        return status, {}, json.dumps({"message": "Not Found" if status == 404 else "Server Error"}).encode("utf-8")


def ask(github, repository=REPOSITORY, token=TOKEN):
    """(exit code, stdout, stderr) of adopted.main on the fake GitHub."""
    out, err = io.StringIO(), io.StringIO()
    environ = {"GH_TOKEN": token} if token else {}
    with mock.patch.dict(os.environ, environ, clear=True), contextlib.redirect_stdout(out), \
            contextlib.redirect_stderr(err):
        code = adopted.main([repository], transport=github)
    return code, out.getvalue(), err.getvalue()


class TheScript(unittest.TestCase):
    def test_a_repository_with_the_protocols_text_is_adopted(self):
        github = FakeGitHub(200)
        code, out, err = ask(github)
        self.assertEqual((code, out, err), (adopted.ADOPTED, "the repository is adopted already\n", ""))
        self.assertEqual([(method, path) for method, path, _ in github.calls], [("GET", PROTOCOL)])
        self.assertEqual(github.calls[0][2]["Authorization"], f"Bearer {TOKEN}")

    def test_a_repository_without_it_has_no_adoption_yet(self):
        code, out, err = ask(FakeGitHub(404))
        self.assertEqual((code, out, err), (0, "the repository has no adoption yet\n", ""))

    def test_the_answer_is_the_sweeps_own_rule(self):
        """One rule for the three paths: the script decides by
        sweep.is_adopted, and the same answers make the sweep skip the
        repository as adopted."""
        for found, code in ((True, adopted.ADOPTED), (False, 0)):
            with self.subTest(found=found), mock.patch.object(sweep, "is_adopted", return_value=found) as rule:
                self.assertEqual(ask(FakeGitHub())[0], code)
                (github, repository), _ = rule.call_args
                self.assertEqual((github.token, repository), (TOKEN, {"full_name": REPOSITORY}))
        record = {"id": 1, "full_name": REPOSITORY, "owner": {"login": OWNER}, "default_branch": "main"}
        settings = sweep.Settings("OpenSpineConsortium", frozenset(), 0, 420)

        def answers(status):
            def transport(method, url, headers, body):
                path = url.removeprefix(sweep.API)
                if path.endswith("/branches/main"):
                    return 200, {}, b"{}"
                if "/git/matching-refs/" in path or "/pulls?" in path or "/issues?" in path:
                    return 200, {}, b"[]"
                return FakeGitHub(status)(method, url, headers, body)
            return transport

        self.assertEqual(sweep.why_skipped(sweep.GitHub("t", answers(200)), record, settings, "bot"), sweep.ADOPTED)
        self.assertNotEqual(sweep.why_skipped(sweep.GitHub("t", answers(404)), record, settings, "bot"), sweep.ADOPTED)

    def test_a_refusal_that_is_not_a_clean_404_is_an_error_that_names_nothing(self):
        for github in (FakeGitHub(500), FakeGitHub(403), FakeGitHub(raising="GitHub could not be reached (URLError)")):
            with self.subTest(status=github.status, raising=github.raising):
                code, out, err = ask(github)
                self.assertEqual((code, out), (1, ""))
                self.assertTrue(err.startswith("adopted: GitHub could not be asked ("), err)
                self.assertEqual(err.count("\n"), 1)
                for word in (OWNER, NAME, TOKEN):
                    self.assertNotIn(word, err)

    def test_no_token_or_a_name_adopt_py_would_not_print_is_refused_before_any_call(self):
        for repository, token in ((REPOSITORY, ""), ("mona/widget?ref=x", TOKEN), ("../widget", TOKEN),
                                  ("mona/widget/contents", TOKEN), ("OpenSpineConsortium/symphony-template", TOKEN)):
            with self.subTest(repository=repository, token=bool(token)):
                github = FakeGitHub(200)
                code, out, err = ask(github, repository, token)
                self.assertEqual((code, out, github.calls), (2, "", []))
                self.assertTrue(err.startswith("adopted: "))
                self.assertNotIn(repository, err)

    def test_the_answer_is_kept_here_and_printed_without_a_question(self):
        """The words of the one answer, which the run gives and adopt.yml
        gives where the Setup App is missing, live in the script: --answer
        prints them and asks GitHub nothing, needing no token and no name,
        and they name nothing, since a repository given by ids may be
        private."""
        github = FakeGitHub(200)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            code = adopted.main(["--answer"], transport=github)
        self.assertEqual((code, out.getvalue(), err.getvalue(), github.calls), (0, adopted.ANSWER + "\n", "", []))
        self.assertTrue(adopted.ANSWER.startswith(ANSWER))
        self.assertTrue(adopted.ANSWER.endswith("; this one is closed."))
        self.assertNotIn("$", adopted.ANSWER)
        adopted.ANSWER.encode("ascii")

    def test_no_name_is_refused_before_any_call(self):
        github = FakeGitHub(200)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"GH_TOKEN": TOKEN}, clear=True), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            code = adopted.main([], transport=github)
        self.assertEqual((code, out.getvalue(), github.calls), (2, "", []))
        self.assertTrue(err.getvalue().startswith("adopted: the repository must be OWNER/NAME"))


def step_script(text, name):
    """The run: block of the step with this name, unindented, as the
    runner hands it to bash."""
    lines = text.split("\n")
    start = next(index for index, line in enumerate(lines) if line.strip() == name or line.strip() == f"- {name}")
    run = next(index for index in range(start, len(lines)) if lines[index].strip() == "run: |")
    body = []
    for line in lines[run + 1:]:
        if line.strip() and not line.startswith(" " * 10):
            break
        body.append(line[10:])
    return "\n".join(body) + "\n"


FAKE_GH = """#!/usr/bin/env python3
# gh, answered as GitHub would answer the step for a repository with a
# commit on main, no branch symphony/adopt and a README alone; every call
# is kept, and issue writes are only kept, except that a close marks the
# issue closed in the file ISSUE_STATE names, which a view reads. BRANCHES
# makes it another repository: none, one with no branch at all; 409, the
# same as GitHub may answer for one, "Git Repository is empty"; others,
# one with branches but none by the default branch's name; unreadable, one
# whose list of branches GitHub fails to give.
import json, os, sys
argv = sys.argv[1:]
with open(os.environ["GH_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(argv) + "\\n")
state = os.environ.get("ISSUE_STATE", "")
branches = os.environ.get("BRANCHES", "")
def refuse(status):
    words = {"404": "Branch not found", "409": "Git Repository is empty.", "500": "Server Error"}[status]
    sys.stderr.write("gh: " + words + " (HTTP " + status + ")\\n")
    sys.exit(1)
if argv[:2] == ["issue", "view"]:
    print(open(state, encoding="utf-8").read().strip() if state and os.path.exists(state) else "OPEN")
elif argv[:2] == ["issue", "close"] and state:
    open(state, "w", encoding="utf-8").write("CLOSED\\n")
elif argv[:1] == ["api"]:
    path = argv[1]
    asked = argv[argv.index("--jq") + 1] if "--jq" in argv else ""
    if path == "repos/" + os.environ["TARGET"] and asked in (".owner.id", ".id"):
        print("583231" if asked == ".owner.id" else "1296269")
    elif path == "repos/" + os.environ["TARGET"]:
        print("default_branch=main")
        print("owner_type=User")
    elif "/git/matching-refs/" in path or "/pulls?" in path:
        print("0")
    elif "/git/trees/" in path:
        print(json.dumps({"tree": [{"path": "README.md", "type": "blob"}], "truncated": False}))
    elif "/branches?" in path:
        if branches in ("409", "unreadable"):
            refuse("409" if branches == "409" else "500")
        print("0" if branches == "none" else "1")
    elif "/branches/" in path:
        if branches:
            refuse("409" if branches == "409" else "404")
    else:
        sys.exit(1)
"""

# The step's call of scripts/adopted.py, which here runs the real script
# on a fake GitHub that answers the contents call with ANSWER_STATUS.
STAND_IN = """import json, os, sys
sys.path.insert(0, {scripts!r})
import adopted, sweep
status = int(os.environ["ANSWER_STATUS"])
with open(os.environ["GH_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(["adopted.py"] + sys.argv[1:] + [os.environ.get("GH_TOKEN", "")]) + "\\n")
def transport(method, url, headers, body):
    if status == 200:
        return 200, {{}}, b'{{"type": "file"}}'
    return status, {{}}, b'{{"message": "Not Found"}}'
sys.exit(adopted.main(sys.argv[1:], transport=transport))
"""


class TheRunsCheck(unittest.TestCase):
    """The target step of adopt-run.yml, run in bash as the runner runs it,
    for a repository named on the form."""

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        scripts = self.root / "start/scripts"
        scripts.mkdir(parents=True)
        for name in ("refuse.sh", "sweep.py"):
            shutil.copy(SCRIPTS / name, scripts / name)
        (scripts / "adopted.py").write_text(STAND_IN.format(scripts=str(SCRIPTS)), encoding="utf-8")
        bin_folder = self.root / "bin"
        bin_folder.mkdir()
        (bin_folder / "gh").write_text(FAKE_GH, encoding="utf-8")
        (bin_folder / "gh").chmod(0o755)
        # The step's python3, and the fake gh's, is the interpreter of the tests.
        (bin_folder / "python3").symlink_to(sys.executable)
        (self.root / "runner").mkdir()
        self.text = RUN.read_text(encoding="utf-8")

    def run_step(self, status, **more):
        """(exit code, GITHUB_ENV's lines, the calls made, what it printed),
        with the contents call answering status and more of the job's
        environment as given."""
        runner = self.root / "runner"
        for name in ("env", "output", "gh.log"):
            (runner / name).write_text("", encoding="utf-8")
        environ = {
            "PATH": f"{self.root / 'bin'}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "GH_LOG": str(runner / "gh.log"), "ANSWER_STATUS": str(status),
            "TOKEN_OUTCOME": "success", "GH_TOKEN": TOKEN, "ISSUE_TOKEN": "issue-token", "ISSUE": "7", "SOURCE": "issue",
            "GITHUB_REPOSITORY": "OpenSpineConsortium/symphony-start", "TARGET": REPOSITORY, "OWNER": OWNER,
            "MODE_GIVEN": "read", "NAMED": "public", "REQUESTER": OWNER, "KIND_READ": "false", "SAID": REPOSITORY,
            "PULLS_LINK": f"https://github.com/{REPOSITORY}/pulls",
            "BRANCHES_LINK": f"https://github.com/{REPOSITORY}/branches",
            "RUNNER_TEMP": str(runner), "GITHUB_ENV": str(runner / "env"), "GITHUB_OUTPUT": str(runner / "output"),
            **more,
        }
        script = self.root / "step.sh"
        script.write_text(step_script(self.text, TARGET_STEP), encoding="utf-8")
        done = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", str(script)], cwd=self.root,
                              env=environ, capture_output=True, text=True)
        calls = [json.loads(line) for line in (runner / "gh.log").read_text(encoding="utf-8").splitlines()]
        return done.returncode, (runner / "env").read_text(encoding="utf-8").splitlines(), calls, done.stdout

    def test_an_adopted_repository_is_refused_with_one_answer_and_nothing_more_is_read(self):
        code, env, calls, out = self.run_step(200)
        self.assertEqual(code, 0, out)
        self.assertIn("ADOPTED=true", env)
        self.assertIn("REFUSED=true", env)
        self.assertFalse([line for line in env if line.startswith("MODE=")], "the kind is never read")
        self.assertIn(["adopted.py", REPOSITORY, TOKEN], calls)
        comment, = [call for call in calls if call[:2] == ["issue", "comment"]]
        answer = comment[comment.index("--body") + 1]
        self.assertTrue(answer.startswith(ANSWER), answer)
        self.assertTrue(answer.endswith("; this one is closed."))
        self.assertIn("OpenSpineConsortium/symphony-protocol", answer)
        self.assertIn("open a new request with the form naming that one", answer)
        # The reason holds for every kind, and the answer says how to adopt
        # it again, the other kind or what its pull request left out alike.
        self.assertIn("put the template's files over the ones the repository has made its own since, or, for the"
                      " protocol alone, bring back what it has taken out", answer)
        self.assertIn("what the adoption's pull request did not write, its notes say how to add", answer)
        self.assertIn("To adopt it again, as the other kind or with what was left out, first revert that adoption's"
                      " merge on the default branch, so docs/agents/PROTOCOL.md is gone from it, or rename that file if"
                      " it is one of your own and not this protocol, then ask again", answer)
        # The Setup App the form asked for, and the topic the extension reads.
        self.assertIn("Symphony Setup, where it was installed for this request, did nothing here: it uninstalls itself"
                      " as this run ends where this repository is the only one it was given", answer)
        self.assertIn("add the topic symphony with the gear beside About", answer)
        for word in (OWNER, NAME, "https://github.com/" + OWNER):
            self.assertNotIn(word, answer)
        self.assertIn(["issue", "close", "7", "--repo", "OpenSpineConsortium/symphony-start", "--reason", "not planned"],
                      calls)
        asked = [call[1] for call in calls if call[:1] == ["api"]]
        self.assertFalse([path for path in asked if "matching-refs" in path or "/git/trees/" in path], asked)

    def test_the_answer_is_one_whatever_the_kind_asked_and_the_path(self):
        """The same words for Auto, the whole template and the protocol
        alone, and for a repository given by ids, whose name the run masks
        and whose answers say "your repository"."""
        answers = set()
        for more in ({"MODE_GIVEN": "read"}, {"MODE_GIVEN": "new"}, {"MODE_GIVEN": "existing"},
                     {"NAMED": "masked", "SAID": "your repository", "PULLS_LINK": "", "BRANCHES_LINK": ""}):
            with self.subTest(**more):
                code, env, calls, out = self.run_step(200, **more)
                self.assertEqual(code, 0, out)
                self.assertIn("REFUSED=true", env)
                comment, = [call for call in calls if call[:2] == ["issue", "comment"]]
                answers.add(comment[comment.index("--body") + 1])
        self.assertEqual(len(answers), 1, answers)

    def test_a_repository_with_no_adoption_goes_on_to_its_kind(self):
        code, env, calls, out = self.run_step(404)
        self.assertEqual(code, 0, out)
        self.assertIn("MODE=new", env)
        self.assertFalse([line for line in env if line.startswith(("REFUSED=", "ADOPTED="))])
        self.assertFalse([call for call in calls if call[:1] == ["issue"]])

    def test_a_question_github_does_not_answer_stops_the_run_red_without_an_answer(self):
        code, env, calls, out = self.run_step(500)
        self.assertEqual(code, 1)
        self.assertIn("whether the repository is adopted already could not be read: adopted: GitHub could not be asked",
                      out)
        self.assertFalse([line for line in env if line.startswith(("REFUSED=", "ADOPTED=", "MODE="))])
        self.assertFalse([call for call in calls if call[:1] == ["issue"]])

    def test_the_check_comes_after_the_commit_and_before_the_branch_and_the_kind(self):
        """A merged adoption that kept its branch is told it is adopted,
        not sent to delete the branch and ask again."""
        script = step_script(self.text, TARGET_STEP)
        order = [script.index(words) for words in ('has no commit yet', 'python3 start/scripts/adopted.py "$TARGET"',
                                                   'taken="$(', 'mode="$MODE_GIVEN"')]
        self.assertEqual(order, sorted(order))
        self.assertIn('3) echo "ADOPTED=true" >> "$GITHUB_ENV"\n     bash start/scripts/refuse.sh'
                      ' "$(python3 start/scripts/adopted.py --answer)"\n     exit 0 ;;', script)
        self.assertNotIn(ANSWER, script, "the words are the script's, in one place")

    def test_on_the_sweeps_path_an_adopted_repository_is_told_nothing(self):
        """The sweep's own checks pass an adopted repository over, so the
        issue the App opens for a refused sweep is never opened for one."""
        tell = step_script(self.text, TELL_STEP)
        self.assertLess(tell.index('if [ "${ADOPTED:-}" = true ]; then'), tell.index("gh issue create"))
        code = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", tell],
                              env={"PATH": f"{self.root / 'bin'}:{os.environ.get('PATH', '')}", "ADOPTED": "true",
                                   "GH_LOG": str(self.root / "runner/tell.log"), "TARGET": REPOSITORY},
                              capture_output=True, text=True)
        self.assertEqual(code.returncode, 0, code.stdout + code.stderr)
        self.assertIn("nothing to tell", code.stdout)
        self.assertFalse((self.root / "runner/tell.log").exists(), "gh was never called")


UNINSTALL_STEP = "name: Uninstall the Setup App when this was its only repository"
STAGE_STEP = "name: Stage the adoption and write the pull request's title"

FAKE_CURL = """#!/usr/bin/env python3
# curl, answered as GitHub answers the uninstall step for the Setup App's
# installation 42 on the repository, its repository selection and its
# count given; every call is kept.
import json, os, sys
argv, method, out, write_out, url = sys.argv[1:], "GET", None, None, None
index = 0
while index < len(argv):
    word = argv[index]
    if word in ("-X", "-o", "-w", "-H", "-d"):
        method = argv[index + 1] if word == "-X" else method
        out = argv[index + 1] if word == "-o" else out
        write_out = argv[index + 1] if word == "-w" else write_out
        index += 2
        continue
    url = word if word.startswith("https://") else url
    index += 1
with open(os.environ["CURL_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps([method, url]) + "\\n")
api = "https://api.github.com"
answers = {
    ("GET", api + "/repos/" + os.environ["TARGET"] + "/installation"):
        {"id": 42, "repository_selection": os.environ["SELECTION"]},
    ("POST", api + "/app/installations/42/access_tokens"): {"token": "metadata-token"},
    ("GET", api + "/installation/repositories?per_page=2"): {"total_count": int(os.environ["COUNT"])},
}
body = json.dumps(answers.get((method, url), {}))
if out is None:
    sys.stdout.write(body)
elif out != "/dev/null":
    with open(out, "w", encoding="utf-8") as kept:
        kept.write(body)
if write_out == "%{http_code}":
    sys.stdout.write("204")
"""

# The stage step's call of scripts/adopt.py: apply ends with APPLY_STATUS,
# and body prints a title; every call is kept.
STAND_IN_ADOPT = """import json, os, sys
with open(os.environ["GH_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(["adopt.py"] + sys.argv[1:]) + "\\n")
if sys.argv[1] == "apply":
    sys.exit(int(os.environ["APPLY_STATUS"]))
print("Take up the Symphony claim protocol")
"""


def make_runner(root, adopt_stand_in=None):
    """A scratch runner under root: gh, curl and the tests' python3 first on
    PATH, refuse.sh and a stand-in jwt.sh under start/scripts, and, when
    given, a stand-in for scripts/adopt.py."""
    scripts = root / "start/scripts"
    scripts.mkdir(parents=True)
    shutil.copy(SCRIPTS / "refuse.sh", scripts / "refuse.sh")
    (scripts / "jwt.sh").write_text("#!/usr/bin/env bash\necho a.jwt.for.tests\n", encoding="utf-8")
    if adopt_stand_in:
        (scripts / "adopt.py").write_text(adopt_stand_in, encoding="utf-8")
    bin_folder = root / "bin"
    bin_folder.mkdir()
    for name, text in (("gh", FAKE_GH), ("curl", FAKE_CURL)):
        (bin_folder / name).write_text(text, encoding="utf-8")
        (bin_folder / name).chmod(0o755)
    (bin_folder / "python3").symlink_to(sys.executable)
    (root / "runner").mkdir()
    return root / "runner"


def run_script(root, script, environ):
    """(exit code, stdout) of a step's script run in bash as the runner runs
    it, from root, with PATH led by root's bin."""
    path = root / "step.sh"
    path.write_text(script, encoding="utf-8")
    environ = dict(environ, PATH=f"{root / 'bin'}:{os.environ.get('PATH', '/usr/bin:/bin')}")
    done = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", str(path)], cwd=root, env=environ,
                          capture_output=True, text=True)
    return done.returncode, done.stdout + done.stderr


def logged(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def stage_environ(runner, status, said=REPOSITORY):
    """The stage step's environment on a request from the form, with apply
    ending in status."""
    return {"MODE": "existing", "KIND_READ": "true", "TARGET": REPOSITORY, "REQUESTER": OWNER,
            "OWNER_TYPE": "User", "DEFAULT_BRANCH": "main", "METRICS": "on", "SOURCE": "issue",
            "RUNNER_TEMP": str(runner), "GITHUB_ENV": str(runner / "env"), "ISSUE": "7",
            "ISSUE_TOKEN": "issue-token", "GITHUB_REPOSITORY": "OpenSpineConsortium/symphony-start",
            "SAID": said, "GH_LOG": str(runner / "gh.log"), "APPLY_STATUS": str(status)}


class TheSetupAppAfterTheRefusal(unittest.TestCase):
    """The form's paths need Symphony Setup, which the person installs for
    the one run: a request refused because the repository is adopted
    already ends that run, so the Setup App uninstalls itself as after an
    adoption, by the same step, which then has no report to mark."""

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.runner = make_runner(self.root)
        self.text = RUN.read_text(encoding="utf-8")

    def uninstall(self, selection="selected", count=1, app_id="12345", report=None):
        """(exit code, GITHUB_ENV's lines, the curl calls, what it printed)."""
        for name in ("env", "curl.log"):
            (self.runner / name).unlink(missing_ok=True)
        (self.runner / "env").write_text("", encoding="utf-8")
        if report is not None:
            (self.runner / "settings.json").write_text(json.dumps(report), encoding="utf-8")
        environ = {"APP_ID": app_id, "APP_PRIVATE_KEY": "a-key-for-tests", "TARGET": REPOSITORY,
                   "RUNNER_TEMP": str(self.runner), "GITHUB_ENV": str(self.runner / "env"),
                   "CURL_LOG": str(self.runner / "curl.log"), "SELECTION": selection, "COUNT": str(count)}
        code, out = run_script(self.root, step_script(self.text, UNINSTALL_STEP), environ)
        env = (self.runner / "env").read_text(encoding="utf-8").splitlines()
        return code, env, logged(self.runner / "curl.log"), out

    def test_the_step_runs_after_a_refusal_as_adopted_on_the_forms_paths(self):
        step = self.text[self.text.index(UNINSTALL_STEP):]
        condition = step[:step.index("\n        env:")].split("\n")[1].strip()
        self.assertEqual(condition, "if: (env.REFUSED != 'true' && env.SETTINGS == 'applied') || (env.ADOPTED =="
                                    " 'true' && env.SOURCE == 'issue')")

    def test_a_setup_app_on_this_repository_alone_uninstalls_itself(self):
        code, env, calls, out = self.uninstall()
        self.assertEqual(code, 0, out)
        self.assertIn(["DELETE", "https://api.github.com/app/installations/42"], calls)
        self.assertIn("SETUP_UNINSTALLED=true", env)
        self.assertFalse((self.runner / "settings.json").exists(), "no report is made where there was none")

    def test_after_an_adoption_the_report_says_so(self):
        code, env, calls, out = self.uninstall(report={"outcome": "applied"})
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads((self.runner / "settings.json").read_text(encoding="utf-8")),
                         {"outcome": "applied", "uninstalled": True})

    def test_one_that_reaches_more_stays(self):
        for selection, count in (("selected", 2), ("all", 1)):
            with self.subTest(selection=selection, count=count):
                code, env, calls, out = self.uninstall(selection, count)
                self.assertEqual(code, 0, out)
                self.assertNotIn(["DELETE", "https://api.github.com/app/installations/42"], calls)
                self.assertNotIn("SETUP_UNINSTALLED=true", env)
                self.assertIn("stays installed", out)

    def test_a_front_door_without_the_setup_app_asks_nothing(self):
        code, env, calls, out = self.uninstall(app_id="")
        self.assertEqual((code, env, calls), (0, [], []), out)
        self.assertIn("nothing to uninstall", out)


class TheStageStep(unittest.TestCase):
    """apply refuses, with exit status 3, an adoption that could not write
    docs/agents/PROTOCOL.md; the run answers that on the request as a
    refusal that says what to put right, and any other failure of apply
    stays a failure of the run."""

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.runner = make_runner(self.root, STAND_IN_ADOPT)
        self.text = RUN.read_text(encoding="utf-8")

    def stage(self, status, said=REPOSITORY):
        """(exit code, GITHUB_ENV's lines, the calls made, what it printed)."""
        for name in ("env", "gh.log"):
            (self.runner / name).write_text("", encoding="utf-8")
        code, out = run_script(self.root, step_script(self.text, STAGE_STEP), stage_environ(self.runner, status, said))
        env = (self.runner / "env").read_text(encoding="utf-8").splitlines()
        return code, env, logged(self.runner / "gh.log"), out

    def test_a_refusal_of_apply_is_answered_and_nothing_follows(self):
        for said in (REPOSITORY, "your repository"):
            with self.subTest(said=said):
                code, env, calls, out = self.stage(3, said)
                self.assertEqual(code, 0, out)
                self.assertIn("REFUSED=true", env)
                comment, = [call for call in calls if call[:2] == ["issue", "comment"]]
                answer = comment[comment.index("--body") + 1]
                self.assertTrue(answer.startswith("Nothing was done: docs/agents/PROTOCOL.md, the claim protocol's"
                                                  f" text, cannot be written in {said}: its ignore rules match that"
                                                  " file, or a file or link of its own stands where it or its folder"
                                                  " goes."), answer)
                self.assertIn("Stop ignoring it, or move what stands in its way, then open a new request with the"
                              " form", answer)
                self.assertTrue(answer.endswith("; this one is closed."))
                self.assertIn(["issue", "close", "7", "--repo", "OpenSpineConsortium/symphony-start", "--reason",
                               "not planned"], calls)
                self.assertFalse([call for call in calls if call[:2] == ["adopt.py", "body"]])
                self.assertIn("docs/agents/PROTOCOL.md", (self.runner / "refusal").read_text(encoding="utf-8"))

    def test_any_other_failure_of_apply_fails_the_run_without_an_answer(self):
        code, env, calls, out = self.stage(1)
        self.assertEqual(code, 1, out)
        self.assertEqual(env, [])
        self.assertFalse([call for call in calls if call[:1] == ["issue"] or call[:2] == ["adopt.py", "body"]])

    def test_an_adoption_staged_goes_on_to_its_title(self):
        code, env, calls, out = self.stage(0)
        self.assertEqual(code, 0, out)
        self.assertEqual(env, [])
        self.assertIn(["adopt.py", "body", "--title", "--manifest", str(self.runner / "manifest.json")], calls)
        self.assertEqual((self.runner / "title").read_text(encoding="utf-8"), "Take up the Symphony claim protocol\n")


SETUP_CHECK_STEP = "name: Check that the Setup App is installed on the repository"
ANSWER_STEP = "name: Answer the request and close it"
ISSUE_CALLS = ("comment", "close", "view")


class TheNamedRequestWithoutTheSetupApp(unittest.TestCase):
    """A named repository without Symphony Setup is refused with the App's
    install link, since installing it is the consent to the settings; but
    one adopted already would be refused by the run once the App was there,
    so the person would grant Administration for nothing. The issue path
    therefore asks scripts/adopted.py first, with the App's token for that
    one repository that reads contents, and gives the run's own answer.
    The step of adopt.yml is run here for real, as the run's are."""

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.runner = make_runner(self.root)
        (self.root / "start/scripts/adopted.py").write_text(STAND_IN.format(scripts=str(SCRIPTS)), encoding="utf-8")
        self.text = ADOPT.read_text(encoding="utf-8")

    def check(self, status, **more):
        """(exit code, GITHUB_ENV's lines, the calls made, what it printed),
        the contents call answering status."""
        for name in ("env", "gh.log"):
            (self.runner / name).write_text("", encoding="utf-8")
        environ = {"SETUP_OUTCOME": "failure", "PROBE_OUTCOME": "success", "CONTENTS_OUTCOME": "success",
                   "CONTENTS_TOKEN": TOKEN, "GH_TOKEN": "account-token", "TARGET": REPOSITORY,
                   "ISSUE_TOKEN": "issue-token", "ISSUE": "7", "GITHUB_REPOSITORY": "OpenSpineConsortium/symphony-start",
                   "RUN": "https://github.com/OpenSpineConsortium/symphony-start/actions/runs/1",
                   "RUNNER_TEMP": str(self.runner), "GITHUB_ENV": str(self.runner / "env"),
                   "GH_LOG": str(self.runner / "gh.log"), "ANSWER_STATUS": str(status), **more}
        code, out = run_script(self.root, step_script(self.text, SETUP_CHECK_STEP), environ)
        env = (self.runner / "env").read_text(encoding="utf-8").splitlines()
        return code, env, logged(self.runner / "gh.log"), out

    def answered(self, calls):
        comment, = [call for call in calls if call[:2] == ["issue", "comment"]]
        return comment[comment.index("--body") + 1]

    def test_an_adopted_repository_gets_the_runs_answer_and_no_install_link(self):
        code, env, calls, out = self.check(200)
        self.assertEqual(code, 0, out)
        self.assertIn("REFUSED=true", env)
        self.assertIn(["adopted.py", REPOSITORY, TOKEN], calls, "asked with the token that reads contents")
        self.assertEqual(self.answered(calls), adopted.ANSWER)
        self.assertIn(["issue", "close", "7", "--repo", "OpenSpineConsortium/symphony-start", "--reason", "not planned"],
                      calls)
        self.assertFalse([call for call in calls if call[:1] == ["api"]], "no id is read for an install link")

    def test_one_with_no_adoption_or_no_answer_is_sent_to_install_the_setup_app(self):
        """A question GitHub does not answer, or a token that could not be
        made, leaves the adopted check to the run, which asks again once the
        Setup App is there."""
        link = (f"https://github.com/apps/symphony-setup/installations/new/permissions?suggested_target_id=583231"
                f"&repository_ids[]=1296269&state={REPOSITORY}")
        for status, more, asked in ((404, {}, True), (500, {}, True), (200, {"CONTENTS_OUTCOME": "failure"}, False)):
            with self.subTest(status=status, **more):
                code, env, calls, out = self.check(status, **more)
                self.assertEqual(code, 0, out)
                self.assertIn("REFUSED=true", env)
                answer = self.answered(calls)
                self.assertTrue(answer.startswith(f"Nothing was done: Symphony Setup is not installed on {REPOSITORY}."))
                self.assertIn(link, answer)
                questions = [call for call in calls if call[:1] == ["adopted.py"]]
                self.assertEqual(questions, [["adopted.py", REPOSITORY, TOKEN]] if asked else [])

    def test_nothing_is_asked_where_the_setup_app_is_there_or_broken(self):
        code, env, calls, out = self.check(200, SETUP_OUTCOME="success", CONTENTS_OUTCOME="", CONTENTS_TOKEN="")
        self.assertEqual((code, env, calls), (0, [], []), out)
        code, env, calls, out = self.check(200, PROBE_OUTCOME="failure", CONTENTS_OUTCOME="", CONTENTS_TOKEN="")
        self.assertEqual(code, 1, out)
        self.assertIn("this front door's Setup App is not working", self.answered(calls))
        self.assertFalse([call for call in calls if call[:1] == ["adopted.py"]])
        self.assertFalse([call for call in calls if call[:2] == ["issue", "close"]], "the owner's to fix; left open")

    def test_the_question_is_asked_with_a_token_that_reads_the_one_repository(self):
        """The main App's token, for the named repository alone, with
        contents read and nothing else, made only once the Setup App's mint
        failed and its probe showed that App works."""
        steps = re.split(r"\n      - (?=uses:|name:)", self.text)
        mint, = [step for step in steps if "id: contents-token" in step]
        self.assertIn("app-id: ${{ vars.SDLC_APP_ID }}", mint)
        self.assertIn("owner: ${{ steps.form.outputs.owner }}\n          repositories: ${{ steps.form.outputs.name }}\n",
                      mint)
        self.assertEqual(re.findall(r"permission-[a-z-]+: \w+", mint), ["permission-contents: read"])
        self.assertIn("steps.setup-token.outcome == 'failure' && steps.setup-probe.outcome == 'success'", mint)
        self.assertIn("continue-on-error: true", mint)
        self.assertNotIn("skip-token-revoke", mint)
        order = [self.text.index(words) for words in ("id: setup-probe", "id: contents-token", SETUP_CHECK_STEP)]
        self.assertEqual(order, sorted(order))
        check = step_script(self.text, SETUP_CHECK_STEP)
        self.assertIn('GH_TOKEN="$CONTENTS_TOKEN" python3 start/scripts/adopted.py "$TARGET"', check)
        self.assertLess(check.index("adopted.py --answer"), check.index('OWNER_ID="$('))


class TheInstallationsAnswer(unittest.TestCase):
    """A form from the install is answered once, by adopt.yml's job answer
    after the run, which answers nothing itself on that path; a run that
    refused its repository has answered the issue already and closed it,
    ending green, so that job says nothing more of an issue no longer open,
    where it would say a pull request is open. The run's stage step, whose
    apply refuses an adoption that could not write the protocol's text,
    and the job's step are run here for real, one after the other, on an
    issue gh keeps the state of."""

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.runner = make_runner(self.root, STAND_IN_ADOPT)
        self.state = self.runner / "issue-state"
        (self.runner / "gh.log").write_text("", encoding="utf-8")
        (self.runner / "env").write_text("", encoding="utf-8")

    def stage(self, status):
        """The run's stage step for this issue; (exit code, what it printed)."""
        environ = dict(stage_environ(self.runner, status, said="your repository"), ISSUE_STATE=str(self.state))
        return run_script(self.root, step_script(RUN.read_text(encoding="utf-8"), STAGE_STEP), environ)

    def answer(self, result="success", merge="true"):
        """The answer job's step; (exit code, what it printed)."""
        environ = {"ISSUE": "7", "COUNT": "1", "RESULT": result, "MERGE": merge, "GH_TOKEN": "issue-token",
                   "RUN": "https://github.com/OpenSpineConsortium/symphony-start/actions/runs/1",
                   "GITHUB_REPOSITORY": "OpenSpineConsortium/symphony-start", "TARGET": REPOSITORY,
                   "GH_LOG": str(self.runner / "gh.log"), "ISSUE_STATE": str(self.state)}
        return run_script(self.root, step_script(ADOPT.read_text(encoding="utf-8"), ANSWER_STEP), environ)

    def issue_calls(self):
        return [call for call in logged(self.runner / "gh.log") if call[:1] == ["issue"] and call[1] in ISSUE_CALLS]

    def body_of(self, call):
        return call[call.index("--body") + 1]

    def test_a_refusal_in_the_run_is_the_last_word_on_the_issue(self):
        code, out = self.stage(3)
        self.assertEqual(code, 0, out)
        code, out = self.answer()
        self.assertEqual(code, 0, out)
        self.assertIn("nothing more to say", out)
        comment, close, view = self.issue_calls()
        self.assertEqual([comment[:2], close[:2], view[:2]], [["issue", "comment"], ["issue", "close"], ["issue", "view"]])
        self.assertTrue(self.body_of(comment).startswith("Nothing was done: docs/agents/PROTOCOL.md, the claim protocol's"
                                                         " text, cannot be written in your repository"))
        self.assertEqual(close[close.index("--reason") + 1], "not planned")

    def test_an_adoption_made_is_answered_and_closed_as_completed(self):
        code, out = self.stage(0)
        self.assertEqual(code, 0, out)
        code, out = self.answer()
        self.assertEqual(code, 0, out)
        view, comment, close = self.issue_calls()
        self.assertEqual(view[:2], ["issue", "view"])
        self.assertTrue(self.body_of(comment).startswith("Done: the pull request is open in your repository, from the"
                                                         " branch symphony/adopt;"))
        self.assertIn(" Each is merged, or has auto-merge armed", self.body_of(comment))
        self.assertEqual(close[close.index("--reason") + 1], "completed")

    def test_a_run_that_failed_is_said_so_and_left_open_unless_a_refusal_closed_it(self):
        code, out = self.answer(result="failure")
        self.assertEqual(code, 0, out)
        view, comment = self.issue_calls()
        self.assertTrue(self.body_of(comment).startswith("At least one of the 1 adoptions stopped with a failure"))
        (self.runner / "gh.log").write_text("", encoding="utf-8")
        self.state.write_text("CLOSED\n", encoding="utf-8")
        code, out = self.answer(result="failure")
        self.assertEqual(code, 0, out)
        self.assertEqual([call[:2] for call in self.issue_calls()], [["issue", "view"]])


class TheReadme(unittest.TestCase):
    def test_the_readme_says_what_the_named_path_does(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("The form never adopts a repository twice", readme)
        self.assertIn("refused when you name it, with one answer that names nothing of it", readme)
        self.assertIn("- scripts/adopted.py asks", readme)


if __name__ == "__main__":
    unittest.main()
