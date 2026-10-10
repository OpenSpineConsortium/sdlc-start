"""apply against a real checkout of the template, when one is named.

The other tests run on a fake template, since this repository is public and
the template is not, and CI here cannot read it. Whoever can, runs these
too: SDLC_TEMPLATE=/path/to/sdlc-template bash scripts/check.sh. Mode new
must leave no placeholder outside the workflows, no marker folder and,
once the template's init empties it, an empty checkpoint block; mode
existing must leave a vendored copy that the library's own check accepts.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from trees import EMPTY_LISTS, P, THEIR_FILES, adopt, apply, checkpoint_lists, make_target, snapshot

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

    def test_existing_mode_leaves_a_copy_the_library_accepts(self):
        target = make_target(self.root / "target", THEIR_FILES)
        code, _, err = apply(TEMPLATE, target, self.manifest, mode="existing")
        self.assertEqual(code, 0, err)
        verified = subprocess.run([sys.executable, "tools/sdlc_protocol/vendoring.py", "verify", "tools"],
                                  cwd=target, capture_output=True, text=True)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)


if __name__ == "__main__":
    unittest.main()
