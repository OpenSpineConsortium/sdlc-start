"""parse takes exactly what the adoption form writes and nothing else: anyone
can open an issue, so a body that is not the form's, a repository name
GitHub would not take, or a value that would smuggle a second line into
$GITHUB_OUTPUT is refused, with a reason that never quotes the issue."""

import re
import unittest

from trees import adopt, run

OPT_OUT = adopt.OPT_OUT_OF_SHARING
PROTOCOL_ONLY = adopt.PROTOCOL_ONLY


def form_body(repository="octo-org/widget", installation="_No response_", opt_out=" ", protocol_only=" ",
              newline="\n"):
    lines = [
        "### Installation", "", installation, "",
        "### Repository", "", repository, "",
        "### Options", "", f"- [{opt_out}] {OPT_OUT}", f"- [{protocol_only}] {PROTOCOL_ONLY}", "",
    ]
    return newline.join(lines)


BAD_REPOSITORIES = (
    "",
    "_No response_",
    "acme",
    "acme/",
    "/widget",
    "a/b/c",
    "a/b; rm -rf /",
    "a/b && curl evil.example",
    "a/b$(id)",
    "a/b`id`",
    "a/b\nmode=existing",
    "https://github.com/octo-org/widget",
    "github.com/octo-org/widget",
    "octo-org/widget.git",
    "octo-org/widget.GIT",
    "-octo/widget",
    "octo-org/..",
    "octo-org/.",
    "octo org/widget",
    "o" * 40 + "/widget",
    "octo-org/" + "w" * 101,
    "octo" + chr(0xE9) + "/widget",
    "octo_org/widget",
    "OpenSpineConsortium/sdlc-template",
    "openspineconsortium/SDLC-START",
)


class GoodForms(unittest.TestCase):
    def test_the_form_as_github_writes_it(self):
        self.assertEqual(adopt.parse_form(form_body()), {
            "repository": "octo-org/widget", "owner": "octo-org", "name": "widget", "installation": "",
            "mode": "read", "metrics": "on",
        })

    def test_the_form_as_the_install_fills_it_in(self):
        """From the install, GitHub fills in the installation and the person
        presses Create: the repository stays empty, which GitHub writes as
        _No response_, the kind is left to the run and sharing is on."""
        fields = adopt.parse_form(form_body(repository="_No response_", installation="5268543"))
        self.assertEqual(fields, {"repository": "", "owner": "", "name": "", "installation": "5268543",
                                  "mode": "read", "metrics": "on"})
        # Both given: the name decides, and the installation comes along.
        fields = adopt.parse_form(form_body(installation="42"))
        self.assertEqual((fields["repository"], fields["installation"]), ("octo-org/widget", "42"))
        # An empty line, which an older issue of the form's shape could hold.
        self.assertEqual(adopt.parse_form(form_body(repository="", installation="7"))["installation"], "7")

    def test_the_two_boxes_opt_out(self):
        fields = adopt.parse_form(form_body(opt_out="x", protocol_only="X"))
        self.assertEqual((fields["mode"], fields["metrics"]), ("existing", "off"))
        self.assertEqual(adopt.parse_form(form_body(opt_out="X"))["metrics"], "off")
        self.assertEqual(adopt.parse_form(form_body(protocol_only="x"))["mode"], "existing")

    def test_carriage_returns(self):
        self.assertEqual(adopt.parse_form(form_body(newline="\r\n", opt_out="x"))["metrics"], "off")

    def test_names_github_allows(self):
        for repository in ("a/b", "Octo-Org/my.project_2", "o" * 39 + "/" + "n" * 100, "octo/.github"):
            with self.subTest(repository=repository):
                self.assertEqual(adopt.parse_form(form_body(repository=repository))["repository"], repository)

    def test_the_command_prints_key_value_lines(self):
        code, out, err = run(["parse"], stdin=form_body())
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines(), [
            "repository=octo-org/widget", "owner=octo-org", "name=widget", "installation=", "mode=read", "metrics=on",
        ])
        code, out, err = run(["parse"], stdin=form_body(repository="_No response_", installation="5268543"))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines(), [
            "repository=", "owner=", "name=", "installation=5268543", "mode=read", "metrics=on",
        ])


class TheNameCommand(unittest.TestCase):
    """The sweep's path brings no form; the name it brings is checked the
    way the form's would be and printed in parse's shape."""

    def test_a_name_github_allows(self):
        code, out, err = run(["name", "Octo-Org/my.project_2"])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines(), ["repository=Octo-Org/my.project_2", "owner=Octo-Org", "name=my.project_2"])

    def test_a_name_that_is_not_one_or_is_the_front_doors_own(self):
        for repository in ("a/b; rm -rf /", "https://github.com/octo-org/widget", "OpenSpineConsortium/sdlc-start", ""):
            with self.subTest(repository=repository):
                code, out, err = run(["name", repository])
                self.assertEqual((code, out), (1, ""))
                self.assertEqual(len(err.splitlines()), 1)
                self.assertNotIn("rm -rf", err)


class BadForms(unittest.TestCase):
    def refused(self, body, quoted=None):
        with self.assertRaises(adopt.FormError) as caught:
            adopt.parse_form(body)
        reason = str(caught.exception)
        self.assertNotIn("\n", reason)
        if quoted and len(quoted) > 3:
            self.assertNotIn(quoted, reason)
        return reason

    def test_repository_names(self):
        for repository in BAD_REPOSITORIES:
            with self.subTest(repository=repository):
                self.refused(form_body(repository=repository), quoted=repository)

    def test_installations_that_are_not_the_number_github_fills_in(self):
        for installation in ("12a", "1 2", "-1", "0x10", "1" * 21, "123\nmode=existing", "https://github.com/settings/installations/5"):
            with self.subTest(installation=installation):
                reason = self.refused(form_body(repository="_No response_", installation=installation), quoted=installation)
                self.assertIn("installation", reason)
        reason = self.refused(form_body(repository="_No response_", installation="_No response_"))
        self.assertIn("installing the App", reason)

    def test_a_box_the_form_does_not_offer(self):
        self.refused(form_body().replace(PROTOCOL_ONLY, "Something else"))
        self.refused(form_body() + "- [x] mode=new\n", quoted="mode=new")
        self.refused(form_body().replace(f"- [ ] {OPT_OUT}", "share"))

    def test_a_missing_an_extra_or_a_repeated_field(self):
        self.refused(form_body().replace("### Options", "### Choices"))
        self.refused(form_body() + "\n### Notes\n\nplease\n")
        self.refused(form_body() + "\n### Repository\n\nocto/other\n")
        self.refused("")
        self.refused("Please adopt octo-org/widget.")

    def test_the_command_says_why_in_one_line_and_prints_nothing(self):
        code, out, err = run(["parse"], stdin=form_body(repository="a/b; rm -rf /"))
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(len(err.splitlines()), 1)
        self.assertNotIn("rm -rf", err)

    def test_no_output_value_can_hold_a_second_line(self):
        code, out, _ = run(["parse"], stdin=form_body(repository="Octo/x.y_z-1"))
        self.assertEqual(code, 0)
        for line in out.splitlines():
            self.assertRegex(line, re.compile(r"^[a-z]+=[A-Za-z0-9._/-]*$"))


if __name__ == "__main__":
    unittest.main()
