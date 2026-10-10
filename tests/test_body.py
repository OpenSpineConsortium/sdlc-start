"""The pull request's text and the labels.

The body is what a person reads before they merge, so it must say what was
added, kept, replaced, merged or not written and why, that LICENSE was not
touched, what is shared and how to turn it off, and what is left to do in
each mode, all of it for the files that landed; it must never link the
template's private repository. The labels come from the template's own
list, all of them for mode new and all but team mode's for mode existing.
"""

import json
import tempfile
import unittest
from pathlib import Path

from trees import SPEC, THEIR_FILES, adopt, apply, make_checkout, make_target, make_template, run, write

PRIVATE_LINK = "github.com/OpenSpineConsortium/sdlc-template"
NO_GIT = {rel: text for rel, text in THEIR_FILES.items() if not rel.startswith(".git/")}


class Body(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.template = make_template(self.root / "template")
        self.manifest = self.root / "manifest.json"

    def body(self, files=None, ignore=None, **options):
        if ignore is None:
            target = make_target(self.root / "target", files)
        else:
            target = make_checkout(self.root / "target", files, ignore)
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
        self.assertIn("gains `extraKnownMarketplaces`, which names the marketplace"
                      " OpenSpineConsortium/sdlc-marketplace, and `enabledPlugins`, which enables its plugin"
                      " `sdlc@sdlc-marketplace`; every key it had stays.", body)
        self.assertIn("claude plugin install sdlc@sdlc-marketplace --scope project", body)
        self.assertIn("https://github.com/octo-org/widget/settings/rules", body)
        self.assertIn("Never target `board`, which the workflows force-push", body)
        self.assertIn("renders the board at https://github.com/octo-org/widget/blob/board/STATE.md", body)
        self.assertIn("as docs/agents/PROTOCOL.md says", body)
        self.assertIn("is the template's own text", body)
        self.assertIn("LICENSE is not touched", body)
        self.assertNotIn("setup-repo.sh", body)

    def test_existing_mode_lists_what_it_kept(self):
        files = dict(THEIR_FILES, **{"docs/agents/claims/README.md": "theirs\n"})
        self.assertIn("Kept as they are", self.body(files, mode="existing"))

    def test_the_settings_line_names_only_what_the_file_gained(self):
        files = dict(THEIR_FILES, **{".claude/settings.json": '{"enabledPlugins": {"sdlc@sdlc-marketplace": false}}\n'})
        body = self.body(files, mode="existing")
        self.assertIn("gains `extraKnownMarketplaces`, which names the marketplace"
                      " OpenSpineConsortium/sdlc-marketplace; its plugin `sdlc@sdlc-marketplace` stays off in"
                      " `enabledPlugins`, as you set it; every key it had stays.", body)
        self.assertNotIn("which enables its plugin", body)
        files = dict(THEIR_FILES, **{".claude/settings.json": '{"enabledPlugins": {"other@market": true}}\n'})
        self.assertIn("and an entry in `enabledPlugins`, which enables its plugin", self.body(files, mode="existing"))

    def test_a_kept_protocol_is_said_so_and_imports_nothing(self):
        files = dict(THEIR_FILES, **{"docs/agents/PROTOCOL.md": "Agents must ask Bob before merging.\n"})
        body = self.body(files, mode="existing")
        self.assertNotIn("gains the section", body)
        self.assertNotIn("is the template's own text", body)
        self.assertIn("is this repository's own and is kept, so the claim protocol's text did not land and `CLAUDE.md`"
                      " gains no section importing it", body)
        self.assertIn("as the sdlc plugin's claim protocol says", body)
        self.assertIn("```markdown\n## How work is claimed\n", body)

    def test_the_librarys_spec_gets_no_note_about_the_templates_text(self):
        spec = write(self.root, "spec/PROTOCOL.md", SPEC)
        body = self.body(THEIR_FILES, mode="existing", protocol_spec=spec)
        self.assertNotIn("is the template's own text", body)
        self.assertIn("gains the section \"How work is claimed\"", body)

    def test_a_held_back_workflow_changes_the_steps(self):
        files = dict(THEIR_FILES, **{"tools/board.py": "theirs\n"})
        body = self.body(files, mode="existing")
        self.assertIn("- `.github/workflows/board.yml`: `tools/board.py` is this repository's own, and the board's"
                      " workflow and its script are brought together or not at all", body)
        self.assertIn("was not written (above), so nothing renders the board", body)
        self.assertNotIn("Never target", body)
        self.assertNotIn("gh workflow run board.yml", body)

    def test_a_kept_board_workflow_goes_on_rendering_the_board(self):
        files = dict(THEIR_FILES, **{".github/workflows/board.yml": "theirs\n", "tools/board.py": "theirs\n"})
        body = self.body(files, mode="existing")
        self.assertIn("`.github/workflows/board.yml` is this repository's own and is kept, so your workflow goes on"
                      " rendering the board", body)
        self.assertNotIn("nothing renders the board", body)
        self.assertNotIn("gh workflow run board.yml", body)

    def test_a_held_back_library_is_listed_on_one_line(self):
        files = dict(THEIR_FILES, **{"tools/VENDORED": "theirs\n"})
        body = self.body(files, mode="existing")
        self.assertIn("- `tools/sdlc_protocol/__init__.py` and `tools/sdlc_protocol/board.py`: `tools/VENDORED` is"
                      " this repository's own, and the vendored library and its record are brought together or not"
                      " at all", body)

    def test_ignored_files_get_what_to_do_instead(self):
        body = self.body({"README.md": "# widget\n"}, ignore=".claude/\nCLAUDE.md\n", mode="existing")
        self.assertIn("- `CLAUDE.md` and `.claude/settings.json`: " + adopt.IGNORED_WHY, body)
        self.assertIn("Files this repository ignores were not written", body)
        self.assertIn("add this section to the `CLAUDE.md` each session reads", body)
        self.assertIn("```markdown\n## How work is claimed\n", body)
        self.assertIn("claude plugin marketplace add OpenSpineConsortium/sdlc-marketplace", body)
        self.assertIn('"sdlc@sdlc-marketplace": true', body)
        self.assertNotIn("gains the section", body)

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
        body = self.body()
        self.assertIn("writes METRICS.json to the branch `metrics`: counts, durations and rates of the protocol at"
                      " work, and never code", body)
        self.assertIn("JUDGE.json, the failure-type frequencies that someone's own judge writes", body)

    def test_the_metrics_sentence_follows_what_landed(self):
        make_template(self.template, metrics=True)
        files = dict(THEIR_FILES, **{".github/workflows/metrics.yml": "theirs\n"})
        body = self.body(files, mode="existing")
        self.assertIn("The metrics workflow was not written (above), so nothing is computed or shared today", body)
        self.assertNotIn("does not carry its metrics workflow yet", body)
        self.assertNotIn("`metrics`, which the workflows", body)
        self.assertIn("Never target `board`, which", body)

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
