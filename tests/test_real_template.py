"""apply against a real checkout of the template, when one is named.

The other tests run on a fake template, since this repository is public and
the template is not, and CI here cannot read it. Whoever can, runs these
too: SDLC_TEMPLATE=/path/to/symphony-template bash scripts/check.sh. Mode new
must leave no placeholder outside the workflows, no marker folder and,
once the template's init empties it, an empty checkpoint block, and read a
setup script that ticks the box for GitHub Actions' pull requests as one;
mode existing must leave a vendored copy that the library's own check
accepts, and workflows whose scripts import only what landed with them and
run there: the template's scripts come to import modules of their own,
which no fake template here can foresee.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from trees import (EMPTY_LISTS, P, REPO, THEIR_FILES, WORKFLOWS, adopt, apply, checkpoint_lists, make_target,
                   run_script, snapshot, unmet_imports)

# A command of a workflow that runs a Python script, and the script.
RUNS_A_SCRIPT = re.compile(r"\bpython3?\s+(?:-\S+\s+)*(\S+\.py)\b")
# What the adopted scripts see when they run here: no switch in the
# environment, so the file the adoption wrote decides, and a proxy that
# answers nothing, so a call to GitHub would fail at once and the test with it.
OFFLINE = {"SDLC_METRICS": "", "HTTPS_PROXY": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9"}

TEMPLATE = os.environ.get("SDLC_TEMPLATE", "")


@unittest.skipUnless(TEMPLATE, "SDLC_TEMPLATE names no checkout of the template")
class RealTemplate(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.manifest = self.root / "manifest.json"

    def test_new_mode_fills_everything(self):
        target = make_target(self.root / "target")
        code, manifest, err = apply(TEMPLATE, target, self.manifest)
        self.assertEqual(code, 0, err)
        self.assertEqual(manifest["replaced"], ["README.md"])
        self.assertFalse((target / ".template").exists())
        self.assertFalse((target / "LICENSE").exists())
        for rel, data in snapshot(target).items():
            if not rel.startswith(".github/workflows/"):
                with self.subTest(rel=rel):
                    self.assertFalse(any(marker.encode() in data for marker in P.values()))

    def test_new_mode_empties_the_checkpoint_block(self):
        init = (Path(TEMPLATE) / adopt.INIT_SCRIPT).read_text(encoding="utf-8")
        if "reset_checkpoint_block" not in init:
            self.skipTest("the template's tools/template_init.py has no reset_checkpoint_block yet")
        target = make_target(self.root / "target")
        code, _, err = apply(TEMPLATE, target, self.manifest)
        self.assertEqual(code, 0, err)
        self.assertEqual(checkpoint_lists((target / "CLAUDE.md").read_text(encoding="utf-8")), EMPTY_LISTS)

    def test_a_setup_script_that_ticks_the_box_is_read_as_one(self):
        """The pull request names the box among the setup script's steps by
        the API path the script calls, so the real script that ticks it
        must be read as one."""
        script = (Path(TEMPLATE) / adopt.SETUP_SCRIPT).read_text(encoding="utf-8")
        if "can_approve_pull_request_reviews" not in script:
            self.skipTest("the template's scripts/setup-repo.sh does not tick the box yet")
        target = make_target(self.root / "target")
        code, manifest, err = apply(TEMPLATE, target, self.manifest)
        self.assertEqual(code, 0, err)
        self.assertTrue(manifest["setup_script_ticks_box"])

    def test_existing_mode_leaves_a_copy_the_library_accepts(self):
        target = make_target(self.root / "target", THEIR_FILES)
        code, _, err = apply(TEMPLATE, target, self.manifest, mode="existing")
        self.assertEqual(code, 0, err)
        verified = subprocess.run([sys.executable, "tools/sdlc_protocol/vendoring.py", "verify", "tools"],
                                  cwd=target, capture_output=True, text=True)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

    def test_existing_mode_brings_everything_its_workflows_scripts_import(self):
        """What the metrics workflow lacked in a repository with files of its
        own: every script a workflow of mode existing runs, and every module
        of the template it reaches, imports only what landed with it, the
        library among them, and Python's own modules."""
        target = make_target(self.root / "target", THEIR_FILES)
        code, manifest, err = apply(TEMPLATE, target, self.manifest, mode="existing")
        self.assertEqual(code, 0, err)
        self.assertTrue(manifest["metrics_workflow"])
        for workflow, script in WORKFLOWS.items():
            with self.subTest(workflow=workflow):
                self.assertIn(workflow, manifest["added"])
                self.assertEqual(unmet_imports(target, script, manifest["added"]), [])

    def test_each_workflow_runs_only_the_script_it_comes_with(self):
        """A workflow comes with the one script adopt.py names for it and that
        script's imports, so another script it came to run would be left
        behind; this says so before an adoption does, for every workflow mode
        existing brings, and of one that comes with no script, that it runs
        none."""
        target = make_target(self.root / "target", THEIR_FILES)
        code, manifest, err = apply(TEMPLATE, target, self.manifest, mode="existing")
        self.assertEqual(code, 0, err)
        workflows = sorted(rel for rel in manifest["added"] if rel.startswith(".github/workflows/"))
        self.assertLessEqual(set(WORKFLOWS), set(workflows))
        for workflow in workflows:
            lines = (target / workflow).read_text(encoding="utf-8").splitlines()
            commands = [line for line in lines if not line.lstrip().startswith("#")]
            run = {found for line in commands for found in RUNS_A_SCRIPT.findall(line)}
            self.assertEqual(run, {WORKFLOWS[workflow]} if workflow in WORKFLOWS else set(), workflow)

    def test_existing_mode_runs_the_metrics_workflows_commands(self):
        """The metrics workflow's two commands, as it runs them, where the
        switch the adoption wrote says off, which calls no API: the record is
        written and the comparison answers. The board's script answers too."""
        target = make_target(self.root / "target", THEIR_FILES)
        code, _, err = apply(TEMPLATE, target, self.manifest, mode="existing", metrics="off")
        self.assertEqual(code, 0, err)
        record = self.root / "METRICS.json"
        done = run_script(target, "tools/metrics.py", "collect", "--repo", REPO, "--out", str(record),
                          "--usage-cache", str(self.root / "usage-records.json"), environ=OFFLINE)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("off", json.loads(record.read_text(encoding="utf-8")).values())
        done = run_script(target, "tools/metrics.py", "unchanged", str(record), str(record), environ=OFFLINE)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        done = run_script(target, "tools/board.py", "--help", environ=OFFLINE)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main()
