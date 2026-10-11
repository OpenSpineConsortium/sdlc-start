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
RULES = "https://github.com/octo-org/widget/settings/rules"
ALL_DONE = {"ruleset": "done", "toggles": "done", "secret_scanning": "done", "push_protection": "done"}


def report(outcome="applied", states=ALL_DONE, details=None, mode="new", private=False, required_check=True):
    """A report as scripts/setup.py writes it."""
    details = details or {}
    return {
        "schema": adopt.SETUP_SCHEMA, "outcome": outcome, "mode": mode, "private": private,
        "ruleset_name": "Protect the default branch" if outcome == "applied" else None,
        "required_check": required_check if outcome == "applied" else False,
        "settings": {key: {"state": state, "detail": details.get(key, "")} for key, state in states.items()}
        if outcome == "applied" else {},
    }


class Body(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.template = make_template(self.root / "template")
        self.manifest = self.root / "manifest.json"

    def body(self, files=None, ignore=None, settings=None, **options):
        if ignore is None:
            target = make_target(self.root / "target", files)
        else:
            target = make_checkout(self.root / "target", files, ignore)
        code, manifest, err = apply(self.template, target, self.manifest, **options)
        self.assertEqual(code, 0, err)
        argv = ["body", "--manifest", str(self.manifest)]
        if settings is not None:
            argv += ["--settings", str(write(self.root, "settings.json", json.dumps(settings) + "\n"))]
        code, out, err = run(argv)
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

    def test_without_a_report_the_body_says_nothing_of_the_settings(self):
        body = self.body()
        self.assertNotIn("## Settings", body)
        self.assertNotIn("Setup App", body)
        self.assertIn("2. From a clone", body)

    def test_the_settings_applied_in_new_mode(self):
        body = self.body(settings=report())
        self.assertIn("## Settings\n\nThe OpenSpine SDLC Setup App, which you installed on this repository, applied in"
                      " this run the settings `scripts/setup-repo.sh` applies", body)
        self.assertIn("- The ruleset \"Protect the default branch\" for the default branch: created. It requires a"
                      " pull request that passes the check named \"check\" and blocks force pushes and deletions, and"
                      " nobody can bypass it. This pull request brings that check and runs it where Actions is"
                      " enabled, so it can merge once that is green; if the check never reports, or you close this"
                      f" pull request instead, remove the check from the ruleset, or the ruleset, at {RULES}.", body)
        self.assertIn("- Delete head branches on merge and allow auto-merge: on.", body)
        self.assertIn("- Secret scanning and push protection: on.", body)
        self.assertIn("uninstall it at https://github.com/settings/installations, since it holds Administration", body)
        self.assertIn("2. The GitHub side is set up (Settings above), so `bash scripts/setup-repo.sh` is not needed",
                      body)
        self.assertIn("is done but for GitHub's reading of `.github/CODEOWNERS`", body)
        self.assertIn("--area AREA`, which turns auto-merge off again, and, after reading", body)
        self.assertNotIn("2. From a clone", body)
        self.assertNotIn("add the name of your own check", body)
        self.assertNotIn("written but not enforced", body)
        self.assertNotIn("was used in this run", body)
        self.assertLess(body.index("## Settings"), body.index("## Next steps"))
        self.assertLess(body.index("## What is shared"), body.index("## Settings"))

    def test_an_organization_uninstalls_from_its_own_page(self):
        body = self.body(settings=report(), owner_type="Organization")
        self.assertIn("uninstall it at https://github.com/organizations/octo-org/settings/installations", body)

    def test_a_private_repositorys_ruleset_is_said_to_be_unenforced_on_free(self):
        body = self.body(settings=report(private=True))
        self.assertIn(f"at {RULES}. On GitHub Free a private repository's ruleset is written but not enforced.", body)

    def test_the_settings_applied_in_existing_mode(self):
        body = self.body(THEIR_FILES, mode="existing", settings=report(mode="existing", required_check=False))
        self.assertIn("applied in this run the settings the template's setup script applies", body)
        self.assertIn("created. It requires a pull request and blocks force pushes and deletions; add the name of"
                      f" your own check to it at {RULES}, so the default branch takes only pull requests that pass"
                      " it.", body)
        self.assertIn("3. The default branch has the ruleset above (Settings), which targets it alone."
                      " Never target `board`, which the workflows force-push.", body)
        self.assertNotIn("3. Protect the default branch", body)
        self.assertNotIn("setup-repo.sh", body)
        self.assertNotIn("check named \"check\"", body)

    def test_a_ruleset_the_repository_had_is_left_and_checked(self):
        body = self.body(settings=report(states=dict(ALL_DONE, ruleset="exists")))
        self.assertIn(f"this repository has one of that name already, which was left as it is; check at {RULES}", body)
        self.assertIn("2. The GitHub side is set up", body)
        body = self.body(THEIR_FILES, mode="existing",
                         settings=report(mode="existing", required_check=False, states=dict(ALL_DONE, ruleset="exists")))
        self.assertIn(f"3. Check the ruleset you have (Settings above) at {RULES}: it should protect", body)

    def test_a_setting_github_refused_is_said_in_its_words_and_left_by_hand(self):
        failed = dict(ALL_DONE, ruleset="failed")
        body = self.body(settings=report(states=failed, details={"ruleset": "HTTP 403: Resource not accessible"}))
        self.assertIn("which you installed on this repository, was used in this run for the settings", body)
        self.assertNotIn("applied in this run", body)
        self.assertIn("- The ruleset \"Protect the default branch\": not created (GitHub said: HTTP 403: Resource not"
                      f" accessible). Protect the default branch, and only it, at {RULES}", body)
        self.assertIn("2. For what the Settings above could not do: from a clone", body)
        self.assertNotIn("2. The GitHub side is set up", body)
        self.assertIn("which turns auto-merge off again", body)
        body = self.body(THEIR_FILES, mode="existing",
                         settings=report(mode="existing", states=failed, details={"ruleset": "HTTP 403: no"}))
        self.assertIn(f"3. Protect the default branch, and only it, at {RULES}", body)
        failed = dict(ALL_DONE, toggles="failed")
        body = self.body(settings=report(states=failed, details={"toggles": "HTTP 403: no"}))
        self.assertIn("- Delete head branches on merge and allow auto-merge: not changed (GitHub said: HTTP 403: no);"
                      " tick both under https://github.com/octo-org/widget/settings.", body)
        self.assertIn("2. For what the Settings above could not do", body)
        self.assertNotIn("which turns auto-merge off again", body)

    def test_secret_scanning_refused_is_usually_the_plan(self):
        states = dict(ALL_DONE, secret_scanning="failed", push_protection="not-tried")
        details = {"secret_scanning": "HTTP 422: Not available.", "push_protection": "secret scanning is not on"}
        body = self.body(settings=report(states=states, details=details))
        self.assertIn("- Secret scanning: not turned on (GitHub said: HTTP 422: Not available.). Usually that is the"
                      " plan or the visibility", body)
        self.assertIn("was used in this run for the settings", body)
        self.assertNotIn("applied in this run", body)
        self.assertIn("https://github.com/octo-org/widget/settings/security_analysis", body)
        self.assertIn("push protection was not tried, since it needs scanning on.", body)
        self.assertIn("2. The GitHub side is set up", body)
        self.assertIn("is done but for secret scanning or push protection, above, and GitHub's reading of"
                      " `.github/CODEOWNERS`", body)
        states = dict(ALL_DONE, push_protection="failed")
        body = self.body(settings=report(states=states, details={"push_protection": "HTTP 422: No."}))
        self.assertIn("- Secret scanning: on. Push protection: not turned on (GitHub said: HTTP 422: No.); turn it on"
                      " under https://github.com/octo-org/widget/settings/security_analysis", body)
        self.assertIn("is done but for secret scanning or push protection, above", body)

    def test_the_setup_app_not_installed(self):
        body = self.body(settings=report(outcome="not-installed"))
        self.assertIn("## Settings\n\nNone of the settings was changed: no token for this repository could be made"
                      " from the OpenSpine SDLC Setup App, which means it is not installed on this repository, or its"
                      " installation does not include it, or GitHub did not answer; so this run could not apply the"
                      " settings `scripts/setup-repo.sh` applies", body)
        self.assertIn("Step 2 of the next steps applies them by hand, with `scripts/setup-repo.sh`.", body)
        self.assertIn("If you did install it, uninstall it now at https://github.com/settings/installations, since"
                      " nothing used it, and say so on your request's issue.", body)
        self.assertIn("2. From a clone", body)
        self.assertNotIn("That was the Setup App's one job", body)
        self.assertNotIn("which turns auto-merge off again", body)
        self.assertNotIn("Nothing of the GitHub side", body)
        body = self.body(THEIR_FILES, mode="existing", settings=report(outcome="not-installed", mode="existing"))
        self.assertIn("the settings the template's setup script applies", body)
        self.assertIn("Step 3 of the next steps protects the default branch; the two toggles are under"
                      " https://github.com/octo-org/widget/settings and secret scanning with push protection under"
                      " https://github.com/octo-org/widget/settings/security_analysis, where the plan offers them.",
                      body)
        self.assertIn(f"3. Protect the default branch, and only it, at {RULES}", body)

    def test_the_front_door_without_a_setup_app(self):
        body = self.body(settings=report(outcome="not-set-up"))
        self.assertIn("None of the settings was changed: this front door has no Setup App yet", body)
        self.assertIn("Step 2 of the next steps applies them by hand", body)
        self.assertIn("2. From a clone", body)
        self.assertNotIn("uninstall", body.replace("uninstalling the App stops it too", ""))

    def test_the_front_doors_setup_app_broken(self):
        body = self.body(settings=report(outcome="front-door-broken"))
        self.assertIn("None of the settings was changed: this front door's Setup App is not working (its id or"
                      " private key there is wrong, it is not installed on the front door's own repository, or GitHub"
                      " did not answer), which is for the front door's owner to put right, and the run has told them",
                      body)
        self.assertIn("If you installed the Setup App, uninstall it now at https://github.com/settings/installations,"
                      " since nothing used it.", body)
        self.assertIn("2. From a clone", body)

    def test_a_settings_step_that_died_before_its_report(self):
        body = self.body(settings=report(outcome="not-reported"), owner_type="Organization")
        self.assertIn("## Settings\n\nThe step that applies the settings stopped before it could say what it did. If"
                      " you installed the Setup App, some of the settings `scripts/setup-repo.sh` applies", body)
        self.assertIn("check https://github.com/octo-org/widget/settings/rules and"
                      " https://github.com/octo-org/widget/settings. Step 2 of the next steps applies them by hand",
                      body)
        self.assertIn("That was the Setup App's one job: uninstall it at"
                      " https://github.com/organizations/octo-org/settings/installations", body)
        self.assertIn("2. From a clone", body)
        self.assertNotIn("which turns auto-merge off again", body)

    def test_a_request_that_was_an_installation(self):
        """The sweep's path: the opening says the installation was the
        request, a note says how the kind was read and how to get the other,
        and CODEOWNERS' note says who the run picked."""
        body = self.body(source="installation", owner_type="Organization", creator="octo-org")
        self.assertIn("because an administrator of octo-org/widget installed the App on it, which the front door"
                      " (https://github.com/OpenSpineConsortium/sdlc-start) takes as the request.", body)
        self.assertNotIn("asked for it on the adoption form", body)
        self.assertIn("No form said which kind to bring: the run read this repository as a new repository, since its"
                      " default branch held nothing but what GitHub makes when it initializes one", body)
        self.assertIn("For the protocol alone instead, close this pull request, delete its branch `sdlc/adopt`, and"
                      " open the form at https://github.com/OpenSpineConsortium/sdlc-start with the other kind.", body)
        self.assertIn("`.github/CODEOWNERS` names `octo-org`, the organization itself, since the run found no"
                      " administrator among the repository's direct collaborators; GitHub marks that line as one it"
                      " cannot resolve, so name a person or a team, because GitHub asks", body)
        body = self.body(source="installation", owner_type="Organization", creator="mona")
        self.assertIn("`.github/CODEOWNERS` names `mona`, the first administrator the run found among the"
                      " repository's direct collaborators, because GitHub asks", body)
        body = self.body(THEIR_FILES, mode="existing", source="installation")
        self.assertIn("read this repository as an existing repository, since its default branch holds files of its"
                      " own. For the whole template instead", body)
        self.assertNotIn("CODEOWNERS", body)
        body = self.body(owner_type="Organization")
        self.assertIn("`.github/CODEOWNERS` names `mona`, who asked for this pull request, because GitHub", body)
        self.assertNotIn("No form said", body)

    def test_a_file_that_is_not_a_report(self):
        self.body()
        for bad in ('{"schema": "something else"}', '{"schema": "sdlc-setup/1", "outcome": "done", "settings": {}}',
                    '{"schema": "sdlc-setup/1", "outcome": "applied", "settings": []}',
                    '{"schema": "sdlc-setup/1", "outcome": "applied", "settings": {"ruleset": {"state": 1}}}',
                    '{"schema": "sdlc-setup/1", "outcome": "applied", "settings": {"ruleset": {"state": "done",'
                    ' "detail": "two\\nlines"}}}', "[]", "null", "{"):
            path = write(self.root, "bad.json", bad + "\n")
            with self.subTest(report=bad):
                code, _, err = run(["body", "--manifest", str(self.manifest), "--settings", str(path)])
                self.assertEqual(code, 1)
                self.assertEqual(len(err.splitlines()), 1)
                self.assertIn("bad.json", err)
                self.assertNotIn("manifest.json", err)
        code, _, err = run(["body", "--manifest", str(write(self.root, "list.json", "[]\n"))])
        self.assertEqual((code, len(err.splitlines())), (1, 1))


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
