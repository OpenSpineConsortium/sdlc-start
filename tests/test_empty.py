"""An empty repository is adopted from the form, and left alone by the sweep.

A repository with no commit names a default branch and has none, so a pull
request has no branch to go into. Asked for on the form, by its name or
chosen for the Setup App from the install, the run begins its history: the
target step reads the repository as empty (no branch at all, or GitHub's
409 for an empty repository) and as new when the kind is left to it, the
history begins in a fresh folder where the checkout would have been, and
the commit step makes the first commit, the App's and with no file, and
pushes it with symphony/adopt in one atomic push, which a first commit of
anyone else's made meanwhile turns away whole. On the sweep's path the
repository is refused, as the sweep never offers one, and a default branch
missing beside branches of the repository's own is no empty repository.
The steps of .github/workflows/adopt-run.yml are run here for real in
bash, with gh answered from a table or from a bare repository on disk that
git pushes to.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_adopted import FAKE_GH, OWNER, REPOSITORY, RUN, SCRIPTS, STAND_IN, TARGET_STEP, TOKEN, step_script  # noqa: E402

INIT_STEP = "name: Begin the history of an empty repository"
COMMIT_STEP = "name: Commit on symphony/adopt and push it as the App"
STAGE_STEP = "name: Stage the adoption and write the pull request's title"
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
BOT = "symphonyboard[bot]"
BOT_ID = "41898282"
# git as the tests need it: no configuration of the person's, no signing,
# and no maintenance of its own in the background, which would race the
# removal of the scratch folder.
GIT_SETTINGS = (("gc.auto", "0"), ("gc.autoDetach", "false"), ("maintenance.auto", "false"),
                ("maintenance.autoDetach", "false"), ("receive.autogc", "false"), ("commit.gpgSign", "false"))


def git_environment(home):
    environ = {"HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
               "GIT_CONFIG_COUNT": str(len(GIT_SETTINGS))}
    for index, (key, value) in enumerate(GIT_SETTINGS):
        environ[f"GIT_CONFIG_KEY_{index}"] = key
        environ[f"GIT_CONFIG_VALUE_{index}"] = value
    return environ


class TheTargetStep(unittest.TestCase):
    """The step that reads the repository, for one with no commit."""

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
        (bin_folder / "python3").symlink_to(sys.executable)
        (self.root / "runner").mkdir()

    def run_step(self, branches="none", **more):
        """(exit code, GITHUB_ENV's lines, the calls made, what it printed,
        the refusal kept for the repository's issue or None)."""
        runner = self.root / "runner"
        for name in ("env", "output", "gh.log"):
            (runner / name).write_text("", encoding="utf-8")
        (runner / "refusal").unlink(missing_ok=True)
        environ = {
            "PATH": f"{self.root / 'bin'}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "GH_LOG": str(runner / "gh.log"), "ANSWER_STATUS": "404", "BRANCHES": branches,
            "TOKEN_OUTCOME": "success", "GH_TOKEN": TOKEN, "ISSUE_TOKEN": "issue-token", "ISSUE": "7", "SOURCE": "issue",
            "GITHUB_REPOSITORY": "OpenSpineConsortium/symphony-start", "TARGET": REPOSITORY, "OWNER": OWNER,
            "MODE_GIVEN": "read", "NAMED": "public", "REQUESTER": OWNER, "KIND_READ": "false", "SAID": REPOSITORY,
            "PULLS_LINK": f"https://github.com/{REPOSITORY}/pulls",
            "BRANCHES_LINK": f"https://github.com/{REPOSITORY}/branches",
            "RUNNER_TEMP": str(runner), "GITHUB_ENV": str(runner / "env"), "GITHUB_OUTPUT": str(runner / "output"),
            **more,
        }
        script = self.root / "step.sh"
        script.write_text(step_script(RUN.read_text(encoding="utf-8"), TARGET_STEP), encoding="utf-8")
        done = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", str(script)], cwd=self.root,
                              env=environ, capture_output=True, text=True)
        calls = [json.loads(line) for line in (runner / "gh.log").read_text(encoding="utf-8").splitlines()]
        refusal = runner / "refusal"
        kept = refusal.read_text(encoding="utf-8") if refusal.exists() else None
        return (done.returncode, (runner / "env").read_text(encoding="utf-8").splitlines(), calls,
                done.stdout + done.stderr, kept)

    def test_an_empty_repository_asked_on_the_form_is_begun_as_a_new_one(self):
        """No branch at all, however GitHub says so, is an empty
        repository: nothing is refused, nothing more is asked of it (it
        holds no file and no branch), and with the kind left to the run it
        is new."""
        for branches in ("none", "409"):
            with self.subTest(branches=branches):
                code, env, calls, out, kept = self.run_step(branches)
                self.assertEqual(code, 0, out)
                self.assertIn("EMPTY=true", env)
                self.assertIn("MODE=new", env)
                self.assertIn("KIND_READ=true", env)
                self.assertFalse([line for line in env if line.startswith(("REFUSED=", "ADOPTED="))], env)
                self.assertIsNone(kept)
                self.assertIn("the repository has no commit yet", out)
                self.assertFalse([call for call in calls if call[:1] in (["issue"], ["adopted.py"])], calls)
                asked = [call[1] for call in calls if call[:1] == ["api"]]
                self.assertFalse([path for path in asked if "matching-refs" in path or "/git/trees/" in path], asked)

    def test_the_kind_the_form_gave_is_kept(self):
        for given in ("new", "existing"):
            with self.subTest(given=given):
                code, env, _, out, _ = self.run_step(MODE_GIVEN=given)
                self.assertEqual(code, 0, out)
                self.assertIn("EMPTY=true", env)
                self.assertIn(f"MODE={given}", env)

    def test_on_the_sweeps_path_an_empty_repository_is_refused(self):
        """The sweep never offers one, since whoever made it empty may be
        about to push a history of their own; were one to reach the run, it
        is refused, and the repository's issue says the form would make the
        commit."""
        code, env, calls, out, kept = self.run_step(SOURCE="installation", ISSUE="")
        self.assertEqual(code, 0, out)
        self.assertIn("REFUSED=true", env)
        self.assertFalse([line for line in env if line.startswith("EMPTY=")])
        self.assertIn("has no commit yet, and a pull request needs a branch to go into", kept)
        self.assertIn("A request on the form makes that first commit itself, or push one of your own", kept)
        self.assertFalse([call for call in calls if call[:1] == ["issue"]])

    def test_a_default_branch_missing_beside_branches_is_refused_on_every_path(self):
        for more in ({}, {"SOURCE": "installation", "ISSUE": ""}):
            with self.subTest(**more):
                code, env, calls, out, kept = self.run_step("others", **more)
                self.assertEqual(code, 0, out)
                self.assertIn("REFUSED=true", env)
                self.assertFalse([line for line in env if line.startswith(("EMPTY=", "MODE="))])
                self.assertIn("has branches, but none by the name its settings give as the default branch", kept)
                self.assertIn("Choose one of its branches as the default branch", kept)
                comments = [call for call in calls if call[:2] == ["issue", "comment"]]
                self.assertEqual(len(comments), 0 if more else 1)

    def test_a_list_of_branches_github_does_not_give_stops_the_run_red(self):
        code, env, calls, out, kept = self.run_step("unreadable")
        self.assertEqual(code, 1)
        self.assertIn("whether the repository has any branch could not be read", out)
        self.assertFalse([line for line in env if line.startswith(("REFUSED=", "EMPTY=", "MODE="))])
        self.assertIsNone(kept)
        self.assertFalse([call for call in calls if call[:1] == ["issue"]])

    def test_a_repository_given_by_ids_is_named_by_nothing(self):
        code, env, calls, out, kept = self.run_step("others", NAMED="masked", SAID="your repository", PULLS_LINK="",
                                                    BRANCHES_LINK="")
        self.assertEqual(code, 0, out)
        comment, = [call for call in calls if call[:2] == ["issue", "comment"]]
        answer = comment[comment.index("--body") + 1]
        self.assertTrue(answer.startswith("Nothing was done: your repository has branches"), answer)
        for word in ("mona", "widget", "main"):
            self.assertNotIn(word, answer)


FIRST_GH = """#!/usr/bin/env python3
# gh for the commit step, answered from the bare repository REMOTE names:
# the App's bot's id, whether a branch is there by its exact name, and
# whether the repository has any branch; issue writes are only kept.
import json, os, subprocess, sys
argv = sys.argv[1:]
with open(os.environ["GH_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(argv) + "\\n")
def heads():
    done = subprocess.run(["git", "ls-remote", "--heads", os.environ["REMOTE"]], capture_output=True, text=True,
                          check=True)
    return [line.split("\\t")[1] for line in done.stdout.splitlines()]
if argv[:1] == ["api"]:
    path = argv[1]
    if path.startswith("users/"):
        print(os.environ["BOT_ID"])
    elif "/git/matching-refs/heads/" in path:
        name = path.split("/git/matching-refs/heads/", 1)[1]
        print(sum(1 for ref in heads() if ref == "refs/heads/" + name))
    elif "/branches?" in path:
        print(min(len(heads()), 1))
    else:
        sys.exit(1)
"""


class TheFirstCommit(unittest.TestCase):
    """The step that begins an empty repository's history and the commit
    step, with a bare repository on disk as the repository on GitHub."""

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        scripts = self.root / "start/scripts"
        scripts.mkdir(parents=True)
        shutil.copy(SCRIPTS / "refuse.sh", scripts / "refuse.sh")
        bin_folder = self.root / "bin"
        bin_folder.mkdir()
        (bin_folder / "gh").write_text(FIRST_GH, encoding="utf-8")
        (bin_folder / "gh").chmod(0o755)
        (bin_folder / "python3").symlink_to(sys.executable)
        (self.root / "home").mkdir()
        self.runner = self.root / "runner"
        self.runner.mkdir()
        for name in ("env", "gh.log"):
            (self.runner / name).write_text("", encoding="utf-8")
        self.remote = self.root / "remote.git"
        # GitHub's HEAD names the default branch, even before it exists.
        self.git("init", "--quiet", "--bare", "--initial-branch", "main", str(self.remote))
        for key, value in GIT_SETTINGS:
            self.git("-C", str(self.remote), "config", key, value)
        self.text = RUN.read_text(encoding="utf-8")

    def environment(self, **more):
        return {
            "PATH": f"{self.root / 'bin'}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            **git_environment(self.root / "home"),
            "GH_LOG": str(self.runner / "gh.log"), "REMOTE": str(self.remote), "BOT_ID": BOT_ID,
            "GH_TOKEN": TOKEN, "SLUG": "symphonyboard", "TARGET": REPOSITORY, "DEFAULT_BRANCH": "main",
            "ISSUE_TOKEN": "issue-token", "ISSUE": "7", "GITHUB_REPOSITORY": "OpenSpineConsortium/symphony-start",
            "GITHUB_WORKSPACE": str(self.root), "RUNNER_TEMP": str(self.runner), "GITHUB_ENV": str(self.runner / "env"),
            "SAID": REPOSITORY, "PULLS_LINK": f"https://github.com/{REPOSITORY}/pulls", **more,
        }

    def git(self, *args, cwd=None):
        done = subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **git_environment(self.root / "home")},
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def run_named(self, name, **more):
        script = self.root / "step.sh"
        script.write_text(step_script(self.text, name), encoding="utf-8")
        done = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", str(script)], cwd=self.root,
                              env=self.environment(**more), capture_output=True, text=True)
        return done.returncode, done.stdout + done.stderr

    def stage(self):
        """What apply would have written, and the title."""
        target = self.root / "target"
        for rel, text in (("README.md", "# widget\n"), ("docs/agents/PROTOCOL.md", "# How work is claimed\n"),
                          (".github/workflows/board.yml", "name: Board\n")):
            (target / rel).parent.mkdir(parents=True, exist_ok=True)
            (target / rel).write_text(text, encoding="utf-8")
        (self.runner / "title").write_text("Adopt the Symphony template\n", encoding="utf-8")

    def begin(self):
        """The history begun as the run begins it, aimed at the bare
        repository instead of GitHub."""
        code, out = self.run_named(INIT_STEP)
        self.assertEqual(code, 0, out)
        self.assertIn("the repository's history begins in this run", out)
        target = self.root / "target"
        self.assertEqual(self.git("-C", str(target), "remote", "get-url", "origin"), f"https://github.com/{REPOSITORY}")
        self.assertEqual(self.git("-C", str(target), "symbolic-ref", "HEAD"), "refs/heads/main")
        self.git("-C", str(target), "remote", "set-url", "origin", str(self.remote))
        self.stage()

    def someone_pushes(self, *branches):
        """A commit of someone else's on each branch named, in the bare
        repository, as if pushed while the run went on."""
        work = self.root / "someone"
        self.git("init", "--quiet", "--initial-branch", "main", str(work))
        (work / "notes.md").write_text("their own\n", encoding="utf-8")
        self.git("-C", str(work), "add", "notes.md")
        self.git("-C", str(work), "-c", "user.name=Mona", "-c", "user.email=mona@example.com", "commit", "--quiet",
                 "-m", "Their first commit")
        for branch in branches:
            self.git("-C", str(work), "push", "--quiet", str(self.remote), f"HEAD:refs/heads/{branch}")
        return self.git("-C", str(work), "rev-parse", "HEAD")

    def remote_heads(self):
        listed = self.git("ls-remote", "--heads", str(self.remote))
        return dict(reversed(line.split("\t")) for line in listed.splitlines())

    def env_lines(self):
        return (self.runner / "env").read_text(encoding="utf-8").splitlines()

    def answers(self):
        calls = [json.loads(line) for line in (self.runner / "gh.log").read_text(encoding="utf-8").splitlines()]
        return [call[call.index("--body") + 1] for call in calls if call[:2] == ["issue", "comment"]]

    def test_the_first_commit_holds_no_file_and_lands_with_symphony_adopt(self):
        self.begin()
        code, out = self.run_named(COMMIT_STEP, EMPTY="true")
        self.assertEqual(code, 0, out)
        self.assertIn("PUSHED=true", self.env_lines())
        heads = self.remote_heads()
        self.assertEqual(set(heads), {"refs/heads/main", "refs/heads/symphony/adopt"})
        first, adopt = heads["refs/heads/main"], heads["refs/heads/symphony/adopt"]
        # The first commit: no parent, the empty tree, the App's, and saying why.
        self.assertEqual(self.git("--git-dir", str(self.remote), "rev-list", "--parents", "-n", "1", first), first)
        self.assertEqual(self.git("--git-dir", str(self.remote), "rev-parse", f"{first}^{{tree}}"), EMPTY_TREE)
        self.assertEqual(self.git("--git-dir", str(self.remote), "log", "-1", "--format=%an <%ae>|%cn|%s", first),
                         f"{BOT} <{BOT_ID}+{BOT}@users.noreply.github.com>|{BOT}|Begin this repository's history")
        self.assertIn("It holds no file.", self.git("--git-dir", str(self.remote), "log", "-1", "--format=%b", first))
        # The adoption on top of it, with every file staged and nothing else.
        self.assertEqual(self.git("--git-dir", str(self.remote), "rev-parse", f"{adopt}^"), first)
        files = self.git("--git-dir", str(self.remote), "ls-tree", "-r", "--name-only", adopt).splitlines()
        self.assertEqual(sorted(files), [".github/workflows/board.yml", "README.md", "docs/agents/PROTOCOL.md"])
        self.assertEqual(self.answers(), [])
        # git's messages stayed out of the log.
        self.assertNotIn("remote.git", out)

    def test_a_first_commit_made_meanwhile_turns_the_push_away_whole(self):
        """The atomic push takes both branches or neither: someone's own
        first commit stands, and symphony/adopt never lands beside it."""
        self.begin()
        theirs = self.someone_pushes("main")
        code, out = self.run_named(COMMIT_STEP, EMPTY="true")
        self.assertEqual(code, 0, out)
        self.assertIn("REFUSED=true", self.env_lines())
        self.assertFalse([line for line in self.env_lines() if line.startswith("PUSHED=")])
        self.assertEqual(self.remote_heads(), {"refs/heads/main": theirs})
        answer, = self.answers()
        self.assertTrue(answer.startswith(f"Nothing was done: {REPOSITORY} got a first commit of its own while this run"
                                          " was beginning its history"), answer)
        self.assertTrue(answer.endswith("; this one is closed."))

    def test_another_request_that_pushed_first_is_the_one_to_review(self):
        self.begin()
        self.someone_pushes("main", "symphony/adopt")
        code, out = self.run_named(COMMIT_STEP, EMPTY="true")
        self.assertEqual(code, 0, out)
        answer, = self.answers()
        self.assertTrue(answer.startswith(f"Nothing was done: another request for {REPOSITORY} pushed the branch"
                                          " symphony/adopt while this one ran"), answer)

    def test_a_repository_with_a_commit_gets_symphony_adopt_alone(self):
        """The usual path is as before: a checkout of the default branch,
        and one branch pushed on top of it."""
        theirs = self.someone_pushes("main")
        self.git("clone", "--quiet", "--branch", "main", str(self.remote), str(self.root / "target"))
        self.stage()
        code, out = self.run_named(COMMIT_STEP)
        self.assertEqual(code, 0, out)
        self.assertIn("PUSHED=true", self.env_lines())
        heads = self.remote_heads()
        self.assertEqual(heads["refs/heads/main"], theirs)
        self.assertEqual(self.git("--git-dir", str(self.remote), "rev-parse", f"{heads['refs/heads/symphony/adopt']}^"),
                         theirs)

    def test_the_steps_stand_where_the_run_needs_them(self):
        """No checkout of an empty repository, whose history begins in the
        checkout's folder before apply writes into it; the default branch
        reaches the commit step for the atomic push, which only an empty
        repository's run makes."""
        checkout = self.text.index("ref: refs/heads/${{ steps.target.outputs.default_branch }}")
        begin = self.text.index(INIT_STEP)
        stage = self.text.index(STAGE_STEP)
        commit = self.text.index(COMMIT_STEP)
        self.assertLess(checkout, begin)
        self.assertLess(begin, stage)
        self.assertLess(stage, commit)
        self.assertIn("if: env.REFUSED != 'true' && env.EMPTY != 'true'\n", self.text[:checkout])
        self.assertEqual(self.text[:checkout].count("env.EMPTY != 'true'"), 1)
        self.assertIn("if: env.REFUSED != 'true' && env.EMPTY == 'true'\n", self.text[begin:stage])
        step = step_script(self.text, COMMIT_STEP)
        self.assertIn("DEFAULT_BRANCH: ${{ steps.target.outputs.default_branch }}", self.text[commit:])
        self.assertEqual(self.text.count("atomic=(--atomic)"), 1)
        self.assertLess(step.index("git commit --quiet --allow-empty"), step.index("git switch --quiet -c symphony/adopt"))
        self.assertLess(step.index("git switch --quiet -c symphony/adopt"), step.index("add --all --force"))


if __name__ == "__main__":
    unittest.main()
