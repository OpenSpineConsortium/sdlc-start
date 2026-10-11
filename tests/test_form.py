"""The form, the workflows and scripts/adopt.py agree, and the workflows keep
their own rules.

parse matches the form's labels and options word for word, so a change to
one that the other does not follow fails here instead of refusing every
request. Every workflow passes values to its shell steps only through env:,
since an expression inside run: is pasted into the script before bash reads
it, and uses only GitHub's own actions and create-github-app-token, each on
a major tag.
"""

import re
import unittest
from pathlib import Path

from trees import adopt

ROOT = Path(__file__).resolve().parent.parent
FORM = ROOT / ".github/ISSUE_TEMPLATE/adopt.yml"
WORKFLOWS = sorted((ROOT / ".github/workflows").glob("*.yml"))
# GitHub's own actions on a major tag, and this repository's own reusable
# workflow, which the issue path calls.
ALLOWED_ACTIONS = re.compile(r"actions/(checkout|setup-python|create-github-app-token)@v\d+|\./\.github/workflows/adopt-run\.yml")
SETUP_APP_INSTALL = "https://github.com/apps/openspine-sdlc-setup/installations/new"
RUN_KEY = re.compile(r"^(\s*)(?:- )?run:\s*(.*)$")


def run_blocks(text):
    """Each run: script of a workflow as (line number, its text)."""
    lines = text.split("\n")
    for index, line in enumerate(lines):
        found = RUN_KEY.match(line)
        if not found:
            continue
        indent, rest = len(found.group(1)), found.group(2)
        if not rest.startswith(("|", ">")):
            yield index + 1, rest
            continue
        body = []
        for following in lines[index + 1:]:
            if following.strip() and len(following) - len(following.lstrip(" ")) <= indent:
                break
            body.append(following)
        yield index + 1, "\n".join(body)


class TheForm(unittest.TestCase):
    def setUp(self):
        self.text = FORM.read_text(encoding="utf-8")

    def test_every_field_parse_reads_is_a_label_of_the_form(self):
        labels = re.findall(r"^      label: (.+)$", self.text, re.MULTILINE)
        self.assertEqual(labels, list(adopt.FIELDS))

    def test_every_box_parse_reads_is_offered_and_both_are_opt_outs(self):
        """From the install the form is one button: nothing is required,
        the kind is read from the repository and sharing is on unless the
        person ticks the box; the two boxes are the form's only choices."""
        for option in adopt.OPTIONS:
            self.assertIn(f"        - label: {option}\n", self.text)
        self.assertNotIn("type: dropdown", self.text)
        self.assertNotIn("required: true", self.text)
        self.assertEqual(self.text.count("required: false"), 2)
        self.assertLess(self.text.index("    id: installation_id\n"), self.text.index("    id: repository\n"))
        run = (ROOT / ".github/workflows/adopt-run.yml").read_text(encoding="utf-8")
        self.assertIn('if [ "$mode" = read ]; then', run)
        self.assertIn("sweep.classify_tree", run)
        self.assertIn('echo "MODE=$mode" >> "$GITHUB_ENV"', run)
        self.assertIn("env.MODE == 'existing'", run)
        self.assertIn("env.MODE == 'new'", run)
        self.assertEqual(run.count("inputs.mode"), 1)
        self.assertIn("spec+=(--kind-read)", run)

    def test_the_label_and_the_title(self):
        self.assertIn('labels: ["adopt"]\n', self.text)
        self.assertIn('title: "Adopt"\n', self.text)

    def test_the_form_is_short_and_says_what_matters(self):
        """The person is assumed to know what they are doing: a few
        sentences, which still say what is shared, where the switch is,
        that the issue is public and where the App is installed."""
        for words in ("never code, text or names", ".github/sdlc-metrics", "This issue is public", "installations/new",
                      "Press Create", "newest created"):
            self.assertIn(words, self.text)
        prose = re.search(r"value: \|\n((?:        .*\n)+)", self.text).group(1)
        self.assertLess(len(prose.split()), 140)

    def test_the_form_and_the_readme_name_the_setup_app_and_its_one_use(self):
        """Installing the Setup App is the person's consent to the settings,
        so the form says what it is for, where it is and that it is
        uninstalled afterwards, and the README names the same App."""
        for text in (self.text, (ROOT / "README.md").read_text(encoding="utf-8")):
            self.assertIn(SETUP_APP_INSTALL, text)
            self.assertIn("Administration", text)
            self.assertIn("uninstall", text)
            self.assertIn('"Only select repositories"', text)
        self.assertNotIn("Setup App", "\n".join(re.findall(r"^      label: (.+)$", self.text, re.MULTILINE)))

    def test_blank_issues_are_off(self):
        config = (ROOT / ".github/ISSUE_TEMPLATE/config.yml").read_text(encoding="utf-8")
        self.assertIn("blank_issues_enabled: false\n", config)


class TheWorkflows(unittest.TestCase):
    def test_no_expression_inside_a_run_step(self):
        for workflow in WORKFLOWS:
            for line, script in run_blocks(workflow.read_text(encoding="utf-8")):
                with self.subTest(workflow=workflow.name, line=line):
                    self.assertNotIn("${{", script)

    def test_the_scan_sees_run_blocks(self):
        sample = "steps:\n  - run: |\n      echo ${{ github.token }}\n  - name: x\n    run: echo ok\n"
        self.assertEqual([script.strip() for _, script in run_blocks(sample)], ["echo ${{ github.token }}", "echo ok"])

    def test_only_allowed_actions_on_major_tags(self):
        for workflow in WORKFLOWS:
            for used in re.findall(r"uses:\s*(\S+)", workflow.read_text(encoding="utf-8")):
                with self.subTest(workflow=workflow.name, action=used):
                    self.assertRegex(used, ALLOWED_ACTIONS)
                    self.assertTrue(ALLOWED_ACTIONS.fullmatch(used))

    def test_adopt_runs_on_opened_issues_with_the_label(self):
        text = (ROOT / ".github/workflows/adopt.yml").read_text(encoding="utf-8")
        self.assertIn("  issues:\n    types: [opened, reopened]\n", text)
        self.assertIn("if: contains(github.event.issue.labels.*.name, 'adopt')", text)
        self.assertIn("permissions:\n  issues: write\n  contents: read\n", text)
        self.assertIn("group: adopt-${{ github.event.issue.number }}", text)

    def test_the_issue_path_checks_and_then_calls_the_shared_run(self):
        """The adoption itself is one workflow for both paths; the issue
        path hands it the name the form made public, or the ids of a form
        that came from the install, the author and the issue, and only
        after its own checks passed."""
        text = (ROOT / ".github/workflows/adopt.yml").read_text(encoding="utf-8")
        self.assertIn("uses: ./.github/workflows/adopt-run.yml", text)
        self.assertIn("if: needs.request.result == 'success' && needs.request.outputs.refused != 'true'", text)
        self.assertIn("requester: ${{ github.event.issue.user.login }}", text)
        self.assertIn("issue: ${{ github.event.issue.number }}", text)
        self.assertIn("installation_id: ${{ needs.request.outputs.installation }}", text)
        self.assertIn("repository_id: ${{ needs.request.outputs.repository_id }}", text)
        self.assertIn("secrets: inherit", text)
        for word in ("target-token", "template-token", "setup-token", "gh pr create"):
            self.assertNotIn(word, text)

    def test_a_form_from_the_install_is_resolved_silently_and_answered_without_a_name(self):
        """The install fills in the installation's number and no name: the
        issue path lists that installation's repositories with the App's
        JWT, takes the one it holds once the author administers it, gives
        every failure one answer, masks the name and passes ids on; the
        run then names the repository in its answers only when the form
        named it."""
        text = (ROOT / ".github/workflows/adopt.yml").read_text(encoding="utf-8")
        resolve = text.index("name: Resolve the installation's one repository")
        self.assertIn("if: env.REFUSED != 'true' && steps.form.outputs.repository == ''", text[resolve:])
        self.assertIn("bash start/scripts/jwt.sh", text)
        self.assertIn("/app/installations/$INSTALLATION/access_tokens", text)
        self.assertIn("installation/repositories?per_page=100", text)
        self.assertIn('-d \'{"permissions":{"contents":"read"}}\'', text)
        self.assertIn("sweep.chosen(sweep.GitHub(os.environ[\"APP_TOKEN\"]), found)", text)
        self.assertIn('gh api "repositories/$repository_id/collaborators/$AUTHOR/permission"', text)
        self.assertEqual(text.count("refuse_alike\n"), 2)
        self.assertIn("deadline=$((SECONDS + 20))", text)
        self.assertIn('echo "repository_id=$repository_id" >> "$GITHUB_OUTPUT"', text)
        # The request job never learns the name, so it registers no mask of
        # one and nothing it prints can differ between refusals.
        resolve_step = text[resolve:text.index("      - uses: actions/create-github-app-token@v1", resolve)]
        self.assertNotIn("full_name", resolve_step)
        self.assertEqual(resolve_step.count("::add-mask::"), 2)
        for step in ("id: account-token", "id: app-probe", "name: Check that the App reaches the repository"):
            start = text.index(step)
            self.assertIn("steps.form.outputs.repository != ''", text[start:start + 400])
        run = (ROOT / ".github/workflows/adopt-run.yml").read_text(encoding="utf-8")
        call = run.split("  workflow_dispatch:\n")[0]
        for name in ("installation_id", "repository_id"):
            self.assertIn(f"      {name}:\n", call)
        self.assertIn('if [ -n "$ISSUE" ]; then\n            echo "SOURCE=issue"', run)
        self.assertIn('echo "NAMED=$named" >> "$GITHUB_ENV"', run)
        self.assertIn('if [ "$NAMED" = masked ]; then\n            echo "::add-mask::$branch"', run)
        self.assertIn('[ -n "$REQUESTER_GIVEN" ] && echo "::add-mask::$REQUESTER_GIVEN"', run)
        self.assertNotIn("AUTHOR: ${{ env.REQUESTER }}", run)
        self.assertIn('git/trees/$encoded?recursive=1', run)
        self.assertIn('echo "SAID=your repository" >> "$GITHUB_ENV"', run)
        self.assertIn('echo "SAID=$target" >> "$GITHUB_ENV"', run)
        self.assertNotIn('refuse.sh "Nothing was done: $TARGET', run)
        self.assertNotIn('"$refuse" "Nothing was done: $TARGET', run)
        self.assertNotIn("https://github.com/$TARGET/pulls", run)
        self.assertNotIn("https://github.com/$TARGET/settings", run)
        self.assertIn("Done: the pull request is open in $SAID, from the branch sdlc/adopt${PULLS_LINK:+: $PULLS_LINK}.", run)
        form = FORM.read_text(encoding="utf-8")
        self.assertIn("    id: installation_id\n", form)
        self.assertIn("      label: Installation\n", form)
        for field in ("id: repository", "id: installation_id"):
            start = form.index(field)
            self.assertIn("required: false", form[start:start + 600])
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("issues/new?template=adopt.yml`, and tick \"Redirect on update\"", readme)

    def test_the_shared_run_takes_a_name_from_the_issue_and_ids_from_the_sweep(self):
        """A name typed into a public issue is public; a repository the
        sweep found may be private, so the dispatch carries ids and the run
        masks the name before anything prints it."""
        text = (ROOT / ".github/workflows/adopt-run.yml").read_text(encoding="utf-8")
        self.assertIn("  workflow_call:\n", text)
        self.assertIn("  workflow_dispatch:\n", text)
        call, dispatch = text.split("  workflow_dispatch:\n")
        self.assertIn("      repository:\n", call)
        self.assertIn("      issue:\n", call)
        self.assertNotIn("      repository:\n", dispatch.split("permissions:")[0])
        self.assertIn("      installation_id:\n", dispatch)
        self.assertIn("      repository_id:\n", dispatch)
        self.assertIn('echo "::add-mask::$REPOSITORY"', text)
        self.assertIn('echo "::add-mask::${REPOSITORY%%/*}"', text)
        self.assertIn('echo "::add-mask::${REPOSITORY#*/}"', text)
        self.assertIn("python3 start/scripts/adopt.py name", text)
        self.assertIn('"$RUNNER_TEMP/named" >> "$GITHUB_ENV"', text)
        self.assertNotIn("steps.form", text)
        self.assertNotIn("github.event", text)
        self.assertIn("if: env.REFUSED != 'true' && inputs.issue != ''\n", text)
        self.assertIn("if: failure() && env.REFUSED != 'true' && inputs.issue != ''\n", text)
        self.assertIn('--source "$SOURCE"', text)
        self.assertIn("group: adopt-run-${{ inputs.issue || inputs.repository_id }}", text)
        self.assertIn('echo "::add-mask::$requester"', text)
        self.assertIn('echo "::add-mask::$branch"', text)

    def test_the_sweeps_refusal_is_told_in_the_repository_and_the_owner_on_both_paths(self):
        """The sweep has no issue to answer on, so a refusal after the
        repository's token was minted becomes one issue of the App's there,
        which the sweep reads and skips while open; a broken Setup App of
        the front door's is the owner's news whichever path the run took."""
        text = (ROOT / ".github/workflows/adopt-run.yml").read_text(encoding="utf-8")
        told = text.index("name: Tell the repository when the sweep's adoption was refused or failed")
        self.assertIn("if: always() && env.SOURCE == 'installation' && steps.target-token.outcome == 'success'"
                      " && (env.REFUSED == 'true' || job.status == 'failure')", text[told:])
        self.assertIn('echo "PUSHED=true" >> "$GITHUB_ENV"', text)
        self.assertIn('title="OpenSpine SDLC could not open its pull request"', text)
        self.assertIn('"$RUNNER_TEMP/refusal"', text)
        self.assertIn("creator=openspine-sdlc%5Bbot%5D", text)
        self.assertIn("write off in .github/sdlc-adopt", text)
        owner = text.index("name: Tell the owner when this front door's Setup App is not working")
        self.assertIn("if: env.REFUSED != 'true' && env.SETTINGS == 'front-door-broken'\n", text[owner:])
        self.assertNotIn("inputs.issue", text[owner:text.index("name: Say so when something failed")])
        refuse = (ROOT / "scripts/refuse.sh").read_text(encoding="utf-8")
        self.assertIn('if [ -n "${ISSUE:-}" ]; then', refuse)
        self.assertIn('printf \'%s\\n\' "$kept" > "$RUNNER_TEMP/refusal"', refuse)
        self.assertIn('${message%; this one is closed.}', refuse)

    def test_the_sweep_dispatches_ids_only_and_prints_counts(self):
        text = (ROOT / ".github/workflows/sweep.yml").read_text(encoding="utf-8")
        self.assertIn('    - cron: "*/10 * * * *"\n', text)
        self.assertIn("permissions:\n  actions: write\n  contents: read\n  issues: read\n", text)
        self.assertIn("if: vars.SDLC_APP_ID != ''", text)
        self.assertIn("bash scripts/jwt.sh", text)
        self.assertIn('echo "::add-mask::$jwt"', text)
        self.assertIn("gh issue list --repo \"$GITHUB_REPOSITORY\" --label adopt --state open", text)
        self.assertIn('--json body > "$RUNNER_TEMP/requests.json"', text)
        self.assertIn('--requests "$RUNNER_TEMP/requests.json"', text)
        self.assertNotIn("<<", text)
        self.assertIn("--budget-seconds 420", text)
        self.assertIn("python3 scripts/sweep.py", text)
        self.assertIn("if: always() && env.APP_JWT != ''", text)
        self.assertIn("gh workflow run adopt-run.yml", text)
        self.assertIn('-f installation_id="$installation" -f repository_id="$repository" -f mode="$mode"', text)
        self.assertNotIn("full_name", text)
        self.assertIn("timeout-minutes: 10", text)

    def test_the_check_job_is_named_check(self):
        text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("jobs:\n  check:\n", text)
        self.assertIn("run: bash scripts/check.sh", text)

    def test_only_the_setup_app_is_asked_for_administration(self):
        """The main App's tokens never carry Administration: the one mint
        that asks for it is the Setup App's, for the one repository, and
        its key reaches nothing but that mint."""
        text = (ROOT / ".github/workflows/adopt-run.yml").read_text(encoding="utf-8")
        steps = re.split(r"\n      - (?=uses:|name:)", text)
        asking = [step for step in steps if "permission-administration" in step]
        self.assertEqual(len(asking), 1)
        self.assertIn("app-id: ${{ vars.SDLC_SETUP_APP_ID }}", asking[0])
        self.assertIn("private-key: ${{ secrets.SDLC_SETUP_APP_PRIVATE_KEY }}", asking[0])
        self.assertIn("repositories: ${{ env.NAME }}", asking[0])
        self.assertIn("permission-administration: write", asking[0])
        self.assertIn("continue-on-error: true", asking[0])
        self.assertNotIn("permission-contents", asking[0])
        self.assertEqual(text.count("secrets.SDLC_SETUP_APP_PRIVATE_KEY"), 3)
        self.assertIn("secrets.SDLC_SETUP_APP_PRIVATE_KEY != ''", text)
        probe, = [step for step in steps if "id: setup-probe" in step]
        self.assertIn("owner: OpenSpineConsortium\n          repositories: sdlc-start\n", probe)
        self.assertIn("permission-metadata: read", probe)
        self.assertNotIn("administration", probe)
        self.assertIn("steps.setup-token.outcome == 'failure'", probe)
        main_mints = [step for step in steps if "vars.SDLC_APP_ID" in step]
        self.assertTrue(main_mints)
        for step in main_mints:
            self.assertNotIn("administration", step)
        issue_path = (ROOT / ".github/workflows/adopt.yml").read_text(encoding="utf-8")
        self.assertNotIn("administration", issue_path)
        self.assertNotIn("SDLC_SETUP_APP", issue_path)

    def test_the_settings_are_applied_after_the_push_and_before_the_pull_request(self):
        text = (ROOT / ".github/workflows/adopt-run.yml").read_text(encoding="utf-8")
        pushed = text.index("name: Commit on sdlc/adopt and push it as the App")
        applied = text.index("name: Apply the repository's settings where the Setup App is installed")
        revoked = text.index("name: Revoke the Setup App's token")
        written = text.index("name: Write the pull request's text")
        opened = text.index("name: Open the pull request")
        self.assertLess(pushed, applied)
        self.assertLess(applied, revoked)
        self.assertLess(revoked, written)
        self.assertLess(written, opened)
        for why in ("not-set-up", "not-installed", "front-door-broken"):
            self.assertIn(f"why={why}", text)
        self.assertIn("setup.py skip --why not-reported", text)
        self.assertIn("--ruleset template/docs/setup/ruleset-main.json", text)
        self.assertIn('--settings "$RUNNER_TEMP/settings.json"', text)
        self.assertIn('title="Setup App of this front door is not working"', text)
        self.assertIn("gh issue create", text)


if __name__ == "__main__":
    unittest.main()
