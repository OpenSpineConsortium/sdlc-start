"""The pull request's text and the labels.

The body is what a person reads before they merge, so it must say what was
added, kept, replaced or merged, that LICENSE was not touched, what is
shared and how to turn it off, and what is left to do in each mode; it must
never link the template's private repository. The labels come from the
template's own list, all of them for mode new and all but team mode's for
mode existing.
"""

import tempfile
import unittest
from pathlib import Path

from trees import THEIR_FILES, adopt, apply, make_target, make_template, run, write

PRIVATE_LINK = "github.com/OpenSpineConsortium/sdlc-template"


class Body(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.template = make_template(self.root / "template")
        self.manifest = self.root / "manifest.json"

    def body(self, files=None, **options):
        target = make_target(self.root / "target", files)
        code, manifest, err = apply(self.template, target, self.manifest, **options)
        self.assertEqual(code, 0, err)
        code, out, err = run(["body", "--manifest", str(self.manifest)])
        self.assertEqual(code, 0, err)
        out.encode("ascii")
        self.assertNotIn(PRIVATE_LINK, out)
        return out

    def test_new_mode(self):
        body = self.body()
        self.assertIn("the whole OpenSpine SDLC template into octo-org/widget", body)
        self.assertIn("Replaced", body)
        self.assertIn("- `README.md`", body)
        self.assertIn("LICENSE is not touched", body)
        self.assertIn("bash scripts/setup-repo.sh", body)
        self.assertIn("python3 scripts/crowd.py setup octo-org/widget --area AREA", body)
        self.assertIn("docs/setup/crowdsourcing.md", body)
        self.assertNotIn("CODEOWNERS` names", body)

    def test_new_mode_in_an_organization_names_the_code_owner(self):
        self.assertIn("`.github/CODEOWNERS` names `mona`", self.body(owner_type="Organization"))

    def test_existing_mode(self):
        body = self.body(THEIR_FILES, mode="existing")
        self.assertIn("No file of yours is overwritten", body)
        self.assertIn("gains the section \"How work is claimed\"", body)
        self.assertIn("gains `extraKnownMarketplaces` and `enabledPlugins`", body)
        self.assertIn("claude plugin install sdlc@sdlc-marketplace --scope project", body)
        self.assertIn("https://github.com/octo-org/widget/settings/rules", body)
        self.assertIn("LICENSE is not touched", body)
        self.assertNotIn("setup-repo.sh", body)

    def test_existing_mode_lists_what_it_kept(self):
        files = dict(THEIR_FILES, **{"tools/board.py": "theirs\n"})
        self.assertIn("Kept as they are", self.body(files, mode="existing"))

    def test_invalid_settings_get_the_keys_to_add_by_hand(self):
        body = self.body({".claude/settings.json": "{"}, mode="existing")
        self.assertIn("does not parse", body)
        self.assertIn('"sdlc@sdlc-marketplace": true', body)

    def test_sharing_on_without_and_with_the_metrics_workflow(self):
        body = self.body()
        self.assertIn("Sharing of anonymous aggregates is on", body)
        self.assertIn("does not carry its metrics workflow yet", body)
        self.assertIn("write `off` in `.github/sdlc-metrics`", body)
        make_template(self.template, metrics=True)
        self.assertIn("METRICS.json", self.body())

    def test_sharing_off(self):
        body = self.body(metrics="off")
        self.assertIn("Nothing is shared", body)
        self.assertNotIn("Sharing of anonymous aggregates is on", body)

    def test_the_title_per_mode(self):
        self.body()
        self.assertEqual(run(["body", "--title", "--manifest", str(self.manifest)])[1],
                         "Adopt the OpenSpine SDLC template\n")
        self.body(THEIR_FILES, mode="existing")
        self.assertEqual(run(["body", "--title", "--manifest", str(self.manifest)])[1],
                         "Take up the OpenSpine SDLC claim protocol\n")

    def test_a_file_that_is_not_a_manifest(self):
        write(self.root, "other.json", '{"schema": "something else"}\n')
        self.assertEqual(run(["body", "--manifest", str(self.root / "other.json")])[0], 1)

    def test_the_body_fits_a_pull_request(self):
        for index in range(400):
            write(self.template, f"docs/many/page-{index:03d}-with-a-long-name.md", "a page\n")
        self.assertLess(len(self.body()), 65536)


class Labels(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.template = make_template(Path(self.scratch.name) / "template")

    def labels(self, mode):
        code, out, err = run(["labels", "--template", str(self.template), "--mode", mode])
        self.assertEqual(code, 0, err)
        return [line.split("\t") for line in out.splitlines()]

    def test_new_mode_makes_every_label_of_the_template(self):
        labels = self.labels("new")
        self.assertEqual([name for name, _, _ in labels],
                         ["todo", "claimed", "in-review", "blocker", "account:main", "epic", "blocked"])
        self.assertTrue(all(len(colour) == 6 and description for _, colour, description in labels))

    def test_existing_mode_leaves_out_team_mode(self):
        self.assertEqual([label[0] for label in self.labels("existing")],
                         ["todo", "claimed", "in-review", "blocker", "account:main"])

    def test_a_template_without_the_list(self):
        write(self.template, adopt.INIT_SCRIPT, "print('no labels here')\n")
        self.assertEqual(run(["labels", "--template", str(self.template), "--mode", "new"])[0], 1)


if __name__ == "__main__":
    unittest.main()
