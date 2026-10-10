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
ALLOWED_ACTIONS = re.compile(r"actions/(checkout|setup-python|create-github-app-token)@v\d+")
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

    def test_every_option_parse_takes_is_offered(self):
        for option in [*adopt.KINDS, *adopt.SHARING]:
            self.assertIn(f'        - "{option}"\n', self.text)
        self.assertIn(f"        - label: {adopt.APP_INSTALLED}\n          required: true\n", self.text)

    def test_sharing_is_the_default(self):
        share, keep = (self.text.index(f'        - "{option}"\n') for option in adopt.SHARING)
        self.assertLess(share, keep)
        self.assertEqual(adopt.SHARING[list(adopt.SHARING)[0]], "on")
        self.assertIn("      default: 0\n", self.text)

    def test_the_label_and_the_title(self):
        self.assertIn('labels: ["adopt"]\n', self.text)
        self.assertIn('title: "Adopt: "\n', self.text)

    def test_the_form_says_what_is_shared_and_that_the_issue_is_public(self):
        for words in ("salted hash", "Never code, text, titles or names", "`off`", "This issue is public",
                      "throwaway", "closed once it has been handled", "installations/new"):
            self.assertIn(words, self.text)

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
        self.assertIn("  issues:\n    types: [opened]\n", text)
        self.assertIn("if: contains(github.event.issue.labels.*.name, 'adopt')", text)
        self.assertIn("permissions:\n  issues: write\n  contents: read\n", text)
        self.assertIn("group: adopt-${{ github.event.issue.number }}", text)

    def test_the_check_job_is_named_check(self):
        text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("jobs:\n  check:\n", text)
        self.assertIn("run: bash scripts/check.sh", text)


if __name__ == "__main__":
    unittest.main()
