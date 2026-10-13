"""An empty repository asked for on the form gets the README GitHub makes.

A repository with no commit names a default branch and has none, so a pull
request has no branch to go into. The run's target step reads such a
repository as empty (no branch at all, whether GitHub answers the list with
none or with 409) and first makes the commit GitHub's own "Add a README
file" makes, through the contents API; from there it is a repository with a
README alone, adopted like any other, and the stage step tells apply so,
for the pull request to say. The protocol alone, which goes beside code
that is there, is refused a repository with none. A first commit GitHub
refuses, a default branch missing beside branches of the repository's own
and a default branch GitHub fails to answer for are each told apart, and a
repository given by ids is named by nothing in any answer or in the log.
The step is run here for real in bash, with gh answered from a table.
"""

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_adopted import FAKE_GH, OWNER, NAME, REPOSITORY, RUN, SCRIPTS, STAND_IN, TARGET_STEP, TOKEN, step_script  # noqa: E402

STAGE_STEP = "name: Stage the adoption and write the pull request's title"
README = "repos/" + REPOSITORY + "/contents/README.md"


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
        self.runner = self.root / "runner"
        self.runner.mkdir()

    def run_step(self, branches="none", **more):
        """(exit code, GITHUB_ENV's lines, the calls made, what it printed)."""
        for name in ("env", "output", "gh.log"):
            (self.runner / name).write_text("", encoding="utf-8")
        (self.runner / "begun").unlink(missing_ok=True)
        environ = {
            "PATH": f"{self.root / 'bin'}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "GH_LOG": str(self.runner / "gh.log"), "ANSWER_STATUS": "404", "BRANCHES": branches,
            "TOKEN_OUTCOME": "success", "GH_TOKEN": TOKEN, "ISSUE_TOKEN": "issue-token", "ISSUE": "7",
            "GITHUB_REPOSITORY": "OpenSpineConsortium/symphony-start", "TARGET": REPOSITORY, "OWNER": OWNER,
            "NAME": NAME, "MODE_GIVEN": "read", "NAMED": "public", "REQUESTER": OWNER, "KIND_READ": "false",
            "SAID": REPOSITORY, "PULLS_LINK": f"https://github.com/{REPOSITORY}/pulls",
            "BRANCHES_LINK": f"https://github.com/{REPOSITORY}/branches",
            "RUNNER_TEMP": str(self.runner), "GITHUB_ENV": str(self.runner / "env"),
            "GITHUB_OUTPUT": str(self.runner / "output"),
            **more,
        }
        script = self.root / "step.sh"
        script.write_text(step_script(RUN.read_text(encoding="utf-8"), TARGET_STEP), encoding="utf-8")
        done = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", str(script)], cwd=self.root,
                              env=environ, capture_output=True, text=True)
        calls = [json.loads(line) for line in (self.runner / "gh.log").read_text(encoding="utf-8").splitlines()]
        return (done.returncode, (self.runner / "env").read_text(encoding="utf-8").splitlines(), calls,
                done.stdout + done.stderr)

    def answer(self, calls):
        comment, = [call for call in calls if call[:2] == ["issue", "comment"]]
        return comment[comment.index("--body") + 1]

    def readme_calls(self, calls):
        return [call for call in calls if call[:2] == ["api", README]]

    def test_an_empty_repository_gets_the_readme_github_makes_and_is_adopted_as_new(self):
        """No branch at all, however GitHub says so: the run makes the one
        commit GitHub's "Add a README file" makes, the README holding the
        repository's name, and then reads and adopts it as any repository
        with a README alone, as new when the kind is left to it."""
        for branches in ("none", "409"):
            with self.subTest(branches=branches):
                code, env, calls, out = self.run_step(branches)
                self.assertEqual(code, 0, out)
                self.assertIn("BEGAN=true", env)
                self.assertIn("MODE=new", env)
                self.assertFalse([line for line in env if line.startswith(("REFUSED=", "ADOPTED="))], env)
                made, = self.readme_calls(calls)
                self.assertEqual(made[made.index("--method") + 1], "PUT")
                fields = dict(made[i + 1].split("=", 1) for i, word in enumerate(made) if word == "-f")
                self.assertEqual(base64.b64decode(fields["content"]).decode("utf-8"), f"# {NAME}\n")
                self.assertEqual(fields["message"], "Begin with a README")
                self.assertIn("--silent", made)
                # From there the repository is read like any other.
                self.assertIn(["adopted.py", REPOSITORY, TOKEN], calls)
                self.assertTrue([call for call in calls if call[:1] == ["api"] and "/git/trees/" in call[1]])
                self.assertFalse([call for call in calls if call[:1] == ["issue"]])
                self.assertIn("the run made its first, a README", out)

    def test_the_whole_template_asked_for_is_made_the_same_way(self):
        code, env, calls, out = self.run_step(MODE_GIVEN="new")
        self.assertEqual(code, 0, out)
        self.assertIn("BEGAN=true", env)
        self.assertIn("MODE=new", env)

    def test_the_protocol_alone_is_refused_a_repository_with_no_code(self):
        """The protocol goes beside code that is there: with none, the
        person's code goes up first, and the run writes nothing."""
        code, env, calls, out = self.run_step(MODE_GIVEN="existing")
        self.assertEqual(code, 0, out)
        self.assertIn("REFUSED=true", env)
        self.assertFalse([line for line in env if line.startswith(("BEGAN=", "MODE="))])
        self.assertEqual(self.readme_calls(calls), [])
        answer = self.answer(calls)
        self.assertTrue(answer.startswith(f"Nothing was done: {REPOSITORY} has no commit yet, and the protocol alone"
                                          " goes beside code that is there already. Push your code first"), answer)
        self.assertTrue(answer.endswith("; this one is closed."))

    def test_a_first_commit_github_refuses_is_told_with_the_ways_out(self):
        code, env, calls, out = self.run_step(README="refused")
        self.assertEqual(code, 0, out)
        self.assertIn("REFUSED=true", env)
        self.assertFalse([line for line in env if line.startswith(("BEGAN=", "MODE="))])
        answer = self.answer(calls)
        self.assertTrue(answer.startswith(f"Nothing was done: GitHub refused the first commit of {REPOSITORY}, a"
                                          " README on its default branch"), answer)
        self.assertIn("A ruleset on the default branch", answer)
        self.assertIn("Make its first commit yourself (a README is enough), or let the App bypass that ruleset",
                      answer)
        self.assertTrue(answer.endswith("; this one is closed."))

    def test_a_first_commit_of_someone_elses_meanwhile_is_taken_as_it_is(self):
        """The contents call is turned away because the branch is there now:
        the run goes on with what is there and says nothing of a README
        it did not make."""
        code, env, calls, out = self.run_step(README="raced")
        self.assertEqual(code, 0, out)
        self.assertFalse([line for line in env if line.startswith(("REFUSED=", "BEGAN="))], env)
        self.assertIn("MODE=new", env)
        self.assertIn(["adopted.py", REPOSITORY, TOKEN], calls)

    def test_a_default_branch_missing_beside_branches_is_refused(self):
        code, env, calls, out = self.run_step("others")
        self.assertEqual(code, 0, out)
        self.assertIn("REFUSED=true", env)
        self.assertEqual(self.readme_calls(calls), [])
        answer = self.answer(calls)
        self.assertIn("has branches, but none by the name its settings give as the default branch", answer)
        self.assertIn("Choose one of its branches as the default branch", answer)

    def test_a_branch_or_a_list_github_fails_to_give_stops_the_run_red(self):
        """Only a 404, or 409 for an empty repository, says the branch is not
        there: a failure of GitHub's is no answer about the repository, and
        no refusal is given for it."""
        for branches, said in (("flaky", "the default branch could not be read"),
                               ("unreadable", "whether the repository has any branch could not be read")):
            with self.subTest(branches=branches):
                code, env, calls, out = self.run_step(branches)
                self.assertEqual(code, 1)
                self.assertIn(said, out)
                self.assertFalse([line for line in env if line.startswith(("REFUSED=", "BEGAN=", "MODE="))])
                self.assertEqual(self.readme_calls(calls), [])
                self.assertFalse([call for call in calls if call[:1] == ["issue"]])

    def test_a_repository_given_by_ids_is_named_by_nothing(self):
        """Its name goes into its own README and nowhere else: not into an
        answer on the public issue, not into the log."""
        masked = {"NAMED": "masked", "SAID": "your repository", "PULLS_LINK": "", "BRANCHES_LINK": ""}
        for branches, more in (("none", {}), ("none", {"MODE_GIVEN": "existing"}), ("none", {"README": "refused"}),
                               ("others", {})):
            with self.subTest(branches=branches, **more):
                code, env, calls, out = self.run_step(branches, **masked, **more)
                self.assertEqual(code, 0, out)
                for word in (OWNER, NAME):
                    self.assertNotIn(word, out)
                comments = [call for call in calls if call[:2] == ["issue", "comment"]]
                for comment in comments:
                    answer = comment[comment.index("--body") + 1]
                    self.assertIn("your repository", answer)
                    for word in (OWNER, NAME, "main"):
                        self.assertNotIn(word, answer)

    def test_the_stage_step_tells_apply_the_run_began_the_repository(self):
        stage = step_script(RUN.read_text(encoding="utf-8"), STAGE_STEP)
        self.assertIn('if [ "${BEGAN:-}" = true ]; then\n  spec+=(--began)\nfi', stage)
        self.assertLess(stage.index("spec+=(--began)"), stage.index("python3 start/scripts/adopt.py apply"))


if __name__ == "__main__":
    unittest.main()
