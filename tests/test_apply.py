"""apply in both modes, on fake trees and the template's real init script.

Mode new must leave what "Use this template" would: every file filled, the
marker folder gone, a blank checkpoint, a file of theirs the template also
has replaced and listed. Mode existing must change nothing of theirs but
CLAUDE.md, which gains one section, and .claude/settings.json, which gains
two keys. Neither copies LICENSE, follows a link out of the template, or
writes through a link out of the target or into its .git.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from trees import (CREATOR, P, PROTOCOL_ADDED, SPEC, THEIR_CLAUDE, THEIR_FILES, THEIR_SETTINGS, THEIR_SETTINGS_TEXT,
                   adopt, apply, make_target, make_template, snapshot, write)

PLACEHOLDERS = tuple(P.values())


class Scratch(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.template = self.root / "template"
        self.target = self.root / "target"
        self.manifest = self.root / "manifest.json"


class NewMode(Scratch):
    def setUp(self):
        super().setUp()
        make_template(self.template)
        make_target(self.target, {"README.md": "# widget\n", ".git/HEAD": "ref: refs/heads/main\n"})

    def test_a_readme_only_repository_gets_the_whole_template(self):
        code, manifest, err = apply(self.template, self.target, self.manifest)
        self.assertEqual(code, 0, err)
        self.assertEqual(manifest["replaced"], ["README.md"])
        self.assertEqual(manifest["kept"], [])
        self.assertIn("docs/setup/github.md", manifest["added"])
        self.assertEqual((self.target / "README.md").read_text(),
                         "# widget\n\nClone octo-org/widget; the default branch is main.\n")

    def test_the_placeholders_are_filled_outside_the_workflows(self):
        apply(self.template, self.target, self.manifest)
        for rel, data in snapshot(self.target).items():
            with self.subTest(rel=rel):
                text = data.decode("utf-8")
                self.assertFalse(any(marker in text for marker in PLACEHOLDERS))
        self.assertEqual((self.target / "docs/agents/claims/README.md").read_text(),
                         "# Claim files\n\n- Issue: https://github.com/octo-org/widget/issues/N\n")

    def test_the_marker_goes_and_the_checkpoint_is_blank(self):
        apply(self.template, self.target, self.manifest)
        self.assertFalse((self.target / ".template").exists())
        self.assertIn("Nothing has been checkpointed yet", (self.target / ".claude/session.md").read_text())

    def test_the_code_owner_is_the_owner_or_in_an_organization_the_creator(self):
        apply(self.template, self.target, self.manifest, owner_type="User")
        self.assertEqual((self.target / ".github/CODEOWNERS").read_text(), "* @octo-org\n")
        apply(self.template, self.target, self.manifest, owner_type="Organization")
        self.assertEqual((self.target / ".github/CODEOWNERS").read_text(), f"* @{CREATOR}\n")

    def test_no_license_no_git_no_cache(self):
        _, manifest, _ = apply(self.template, self.target, self.manifest)
        self.assertFalse((self.target / "LICENSE").exists())
        self.assertNotIn("LICENSE", manifest["added"] + manifest["replaced"])
        self.assertFalse((self.target / ".git/config").exists())
        self.assertEqual((self.target / ".git/HEAD").read_text(), "ref: refs/heads/main\n")
        self.assertFalse((self.target / "tools/sdlc_protocol/__pycache__").exists())

    def test_a_script_stays_executable(self):
        apply(self.template, self.target, self.manifest)
        self.assertTrue(os.stat(self.target / "scripts/check.sh").st_mode & 0o111)
        self.assertFalse(os.stat(self.target / "README.md").st_mode & 0o111)

    def test_the_metrics_switch_follows_the_form(self):
        for metrics in ("on", "off"):
            with self.subTest(metrics=metrics):
                apply(self.template, self.target, self.manifest, metrics=metrics)
                self.assertEqual((self.target / ".github/sdlc-metrics").read_text(), metrics + "\n")

    def test_a_template_without_metrics_brings_none(self):
        _, manifest, _ = apply(self.template, self.target, self.manifest)
        self.assertFalse(manifest["metrics_workflow"])
        self.assertFalse((self.target / ".github/workflows/metrics.yml").exists())

    def test_a_template_with_metrics_brings_them(self):
        make_template(self.template, metrics=True)
        _, manifest, _ = apply(self.template, self.target, self.manifest)
        self.assertTrue(manifest["metrics_workflow"])
        self.assertIn(".github/workflows/metrics.yml", manifest["added"])
        self.assertIn("tools/metrics.py", manifest["added"])

    def test_a_link_of_theirs_is_replaced_never_written_through(self):
        outside = write(self.root, "outside/notes.md", "their notes\n")
        (self.target / "README.md").unlink()
        (self.target / "README.md").symlink_to(outside)
        _, manifest, _ = apply(self.template, self.target, self.manifest)
        self.assertIn("README.md", manifest["replaced"])
        self.assertFalse((self.target / "README.md").is_symlink())
        self.assertEqual(outside.read_text(), "their notes\n")


class ExistingMode(Scratch):
    def setUp(self):
        super().setUp()
        make_template(self.template)
        make_target(self.target, THEIR_FILES)
        self.before = snapshot(self.target)

    def adopt_existing(self, **options):
        code, manifest, err = apply(self.template, self.target, self.manifest, mode="existing", **options)
        self.assertEqual(code, 0, err)
        return manifest

    def test_nothing_of_theirs_changes_but_claude_md_and_the_settings(self):
        manifest = self.adopt_existing()
        after = snapshot(self.target)
        for rel, data in self.before.items():
            if rel not in (adopt.CLAUDE_MD, adopt.SETTINGS):
                self.assertEqual(after[rel], data, rel)
        self.assertEqual(set(after) - set(self.before), PROTOCOL_ADDED)
        self.assertEqual(set(manifest["added"]), PROTOCOL_ADDED)
        self.assertEqual(manifest["merged"], sorted([adopt.CLAUDE_MD, adopt.SETTINGS]))
        self.assertEqual((manifest["replaced"], manifest["kept"]), ([], []))

    def test_claude_md_gains_the_section(self):
        self.adopt_existing()
        self.assertEqual((self.target / "CLAUDE.md").read_text(), THEIR_CLAUDE + "\n" + adopt.CLAUDE_SECTION)

    def test_the_settings_gain_two_keys_and_keep_theirs(self):
        self.adopt_existing()
        text = (self.target / ".claude/settings.json").read_text()
        settings = json.loads(text)
        self.assertEqual(list(settings), ["permissions", "model", "extraKnownMarketplaces", "enabledPlugins"])
        self.assertEqual({k: settings[k] for k in THEIR_SETTINGS}, THEIR_SETTINGS)
        self.assertEqual(settings["extraKnownMarketplaces"], {"sdlc-marketplace": adopt.MARKETPLACE})
        self.assertEqual(settings["enabledPlugins"], {"sdlc@sdlc-marketplace": True})
        self.assertTrue(text.startswith(THEIR_SETTINGS_TEXT.rstrip()[:-1].rstrip() + ",\n"), "their lines stay")
        self.assertIn('\n    "enabledPlugins": {\n        "sdlc@sdlc-marketplace": true\n    }\n}\n', text)

    def test_a_merge_into_keys_they_have_writes_the_file_again(self):
        write(self.target, ".claude/settings.json", '{"enabledPlugins": {"other@market": true}}\n')
        self.adopt_existing()
        settings = json.loads((self.target / ".claude/settings.json").read_text())
        self.assertEqual(settings["enabledPlugins"], {"other@market": True, "sdlc@sdlc-marketplace": True})
        self.assertIn("sdlc-marketplace", settings["extraKnownMarketplaces"])

    def test_an_empty_object_takes_the_keys(self):
        write(self.target, ".claude/settings.json", "{}\n")
        self.adopt_existing()
        self.assertEqual(json.loads((self.target / ".claude/settings.json").read_text()), {
            "extraKnownMarketplaces": {"sdlc-marketplace": adopt.MARKETPLACE},
            "enabledPlugins": {"sdlc@sdlc-marketplace": True},
        })

    def test_none_of_the_templates_tests_checks_or_documents(self):
        self.adopt_existing()
        for rel in ("tests/test_template.py", "scripts/check.sh", "docs/setup/github.md", "LICENSE",
                    ".github/workflows/template-init.yml", ".github/CODEOWNERS", "tools/template_init.py"):
            self.assertFalse((self.target / rel).exists(), rel)
        self.assertEqual((self.target / ".github/workflows/ci.yml").read_text(), "name: CI\non:\n  push:\n")

    def test_the_protocol_text_is_filled(self):
        manifest = self.adopt_existing()
        self.assertEqual(manifest["protocol_text"], "template")
        self.assertEqual((self.target / "docs/agents/PROTOCOL.md").read_text(),
                         "# How work is claimed\n\nThe queue is on octo-org/widget; pushes to main.\n")

    def test_the_spec_wins_when_the_copy_carries_it(self):
        make_template(self.template, spec=True)
        manifest = self.adopt_existing()
        self.assertEqual(manifest["protocol_text"], "spec")
        self.assertEqual((self.target / "docs/agents/PROTOCOL.md").read_text(), SPEC)

    def test_a_file_that_is_there_is_kept(self):
        write(self.target, "tools/board.py", "their board\n")
        write(self.target, "docs/agents/claims/README.md", "their claims\n")
        manifest = self.adopt_existing()
        self.assertEqual(manifest["kept"], ["docs/agents/claims/README.md", "tools/board.py"])
        self.assertEqual((self.target / "tools/board.py").read_text(), "their board\n")

    def test_metrics_on_and_off(self):
        for metrics in ("on", "off"):
            with self.subTest(metrics=metrics):
                (self.target / ".github/sdlc-metrics").unlink(missing_ok=True)
                self.adopt_existing(metrics=metrics)
                self.assertEqual((self.target / ".github/sdlc-metrics").read_text(), metrics + "\n")

    def test_a_switch_that_is_there_is_kept_and_the_difference_noted(self):
        write(self.target, ".github/sdlc-metrics", "off\n")
        manifest = self.adopt_existing(metrics="on")
        self.assertEqual((self.target / ".github/sdlc-metrics").read_text(), "off\n")
        self.assertIn(".github/sdlc-metrics", manifest["kept"])
        self.assertEqual(len(manifest["notes"]), 1)

    def test_metrics_come_only_with_both_files(self):
        make_template(self.template, metrics=(".github/workflows/metrics.yml",))
        self.assertFalse(self.adopt_existing()["metrics_workflow"])
        self.assertFalse((self.target / ".github/workflows/metrics.yml").exists())
        make_template(self.template, metrics=True)
        manifest = self.adopt_existing()
        self.assertTrue(manifest["metrics_workflow"])
        self.assertTrue((self.target / "tools/metrics.py").exists())


class ExistingModeEdges(Scratch):
    def setUp(self):
        super().setUp()
        make_template(self.template)

    def adopt_existing(self, files):
        make_target(self.target, files)
        code, manifest, err = apply(self.template, self.target, self.manifest, mode="existing")
        self.assertEqual(code, 0, err)
        return manifest

    def test_no_claude_md_and_no_settings_are_made(self):
        manifest = self.adopt_existing({"README.md": "# widget\n"})
        self.assertEqual((self.target / "CLAUDE.md").read_text(), adopt.CLAUDE_SECTION)
        self.assertEqual(json.loads((self.target / ".claude/settings.json").read_text()), {
            "extraKnownMarketplaces": {"sdlc-marketplace": adopt.MARKETPLACE},
            "enabledPlugins": {"sdlc@sdlc-marketplace": True},
        })
        self.assertIn("CLAUDE.md", manifest["added"])
        self.assertIn(".claude/settings.json", manifest["added"])

    def test_invalid_settings_are_left_as_they_were(self):
        manifest = self.adopt_existing({".claude/settings.json": '{"permissions": [,]\n'})
        self.assertEqual((self.target / ".claude/settings.json").read_text(), '{"permissions": [,]\n')
        self.assertTrue(manifest["settings_invalid"])
        self.assertIn(".claude/settings.json", manifest["kept"])

    def test_settings_of_another_shape_are_left_too(self):
        manifest = self.adopt_existing({".claude/settings.json": '{"enabledPlugins": []}\n'})
        self.assertTrue(manifest["settings_invalid"])
        self.assertEqual((self.target / ".claude/settings.json").read_text(), '{"enabledPlugins": []}\n')

    def test_a_plugin_they_turned_off_stays_off(self):
        theirs = json.dumps({"extraKnownMarketplaces": {"sdlc-marketplace": {"source": {}}},
                             "enabledPlugins": {"sdlc@sdlc-marketplace": False}}) + "\n"
        manifest = self.adopt_existing({".claude/settings.json": theirs})
        self.assertEqual((self.target / ".claude/settings.json").read_text(), theirs)
        self.assertIn(".claude/settings.json", manifest["kept"])

    def test_a_claude_md_that_imports_the_protocol_already_is_kept(self):
        theirs = "# Widget\n\n@docs/agents/PROTOCOL.md\n"
        manifest = self.adopt_existing({"CLAUDE.md": theirs})
        self.assertEqual((self.target / "CLAUDE.md").read_text(), theirs)
        self.assertIn("CLAUDE.md", manifest["kept"])

    def test_carriage_returns_in_claude_md_are_kept(self):
        self.adopt_existing({"CLAUDE.md": "# Widget\r\nrules\r\n"})
        data = (self.target / "CLAUDE.md").read_bytes()
        self.assertTrue(data.startswith(b"# Widget\r\nrules\r\n\r\n## How work is claimed\r\n"))
        self.assertNotIn(b"\n", data.replace(b"\r\n", b""))


class Links(Scratch):
    def setUp(self):
        super().setUp()
        make_template(self.template)
        self.outside = self.root / "outside"
        write(self.outside, "secret.md", "a secret outside the template\n")

    def test_a_link_in_the_template_that_leads_out_is_not_followed(self):
        (self.template / "docs/leak.md").symlink_to(self.outside / "secret.md")
        (self.template / "linked").symlink_to(self.outside, target_is_directory=True)
        make_target(self.target)
        code, manifest, err = apply(self.template, self.target, self.manifest)
        self.assertEqual(code, 0, err)
        self.assertFalse((self.target / "docs/leak.md").exists())
        self.assertFalse((self.target / "linked").exists())
        self.assertEqual({item["path"] for item in manifest["skipped"]}, {"docs/leak.md", "linked"})
        for data in snapshot(self.target).values():
            self.assertNotIn(b"a secret outside", data)

    def test_a_link_of_theirs_that_leads_out_is_never_written_through(self):
        make_target(self.target)
        (self.target / "docs").symlink_to(self.outside, target_is_directory=True)
        code, manifest, err = apply(self.template, self.target, self.manifest, mode="existing")
        self.assertEqual(code, 0, err)
        skipped = {item["path"]: item["why"] for item in manifest["skipped"]}
        self.assertIn("docs/agents/PROTOCOL.md", skipped)
        self.assertIn("leads out of the repository", skipped["docs/agents/PROTOCOL.md"])
        self.assertEqual(sorted(p.name for p in self.outside.iterdir()), ["secret.md"])

    def test_a_link_of_theirs_into_git_is_never_written_through(self):
        make_target(self.target, {".git/hooks/README": "hooks\n"})
        (self.target / "tools").symlink_to(self.target / ".git/hooks", target_is_directory=True)
        code, manifest, err = apply(self.template, self.target, self.manifest, mode="existing")
        self.assertEqual(code, 0, err)
        self.assertIn("tools/board.py", {item["path"] for item in manifest["skipped"]})
        self.assertEqual(sorted(p.name for p in (self.target / ".git/hooks").iterdir()), ["README"])

    def test_a_claude_md_link_that_leads_out_is_left_alone(self):
        make_target(self.target)
        (self.target / "CLAUDE.md").symlink_to(self.outside / "secret.md")
        code, manifest, err = apply(self.template, self.target, self.manifest, mode="existing")
        self.assertEqual(code, 0, err)
        self.assertIn("CLAUDE.md", {item["path"] for item in manifest["skipped"]})
        self.assertEqual((self.outside / "secret.md").read_text(), "a secret outside the template\n")

    def test_a_file_where_a_folder_goes_is_left_alone(self):
        make_target(self.target, {"tools": "their tools file\n"})
        code, manifest, err = apply(self.template, self.target, self.manifest, mode="new")
        self.assertEqual(code, 0, err)
        self.assertEqual((self.target / "tools").read_text(), "their tools file\n")
        self.assertIn("tools/board.py", {item["path"] for item in manifest["skipped"]})


class Refusals(Scratch):
    def setUp(self):
        super().setUp()
        make_template(self.template)
        make_target(self.target)

    def test_a_bad_repository_or_creator(self):
        self.assertEqual(apply(self.template, self.target, self.manifest, repo="a/b; rm -rf /")[0], 1)
        code, _, err = apply(self.template, self.target, self.manifest, repo="OpenSpineConsortium/sdlc-template")
        self.assertEqual(code, 1, err)

    def test_a_manifest_inside_the_target(self):
        code, _, err = apply(self.template, self.target, self.target / "manifest.json")
        self.assertEqual(code, 1)
        self.assertIn("outside the target", err)

    def test_nested_trees(self):
        code, _, _ = apply(self.template, self.template / "docs", self.manifest)
        self.assertEqual(code, 1)

    def test_a_template_without_its_init(self):
        (self.template / adopt.INIT_SCRIPT).unlink()
        code, _, err = apply(self.template, self.target, self.manifest)
        self.assertEqual(code, 1)
        self.assertIn("template_init.py", err)
        self.assertEqual(snapshot(self.target), {"README.md": b"# widget\n"})

    def test_an_init_that_fails(self):
        write(self.template, adopt.INIT_SCRIPT, "import sys\nsys.exit('init broke')\n")
        code, _, err = apply(self.template, self.target, self.manifest)
        self.assertEqual(code, 1)
        self.assertIn("init broke", err)
        self.assertEqual(snapshot(self.target), {"README.md": b"# widget\n"})

    def test_existing_mode_needs_the_protocol(self):
        (self.template / "tools/VENDORED").unlink()
        code, _, err = apply(self.template, self.target, self.manifest, mode="existing")
        self.assertEqual(code, 1)
        self.assertIn("tools/VENDORED", err)


if __name__ == "__main__":
    unittest.main()
