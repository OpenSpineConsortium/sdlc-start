#!/usr/bin/env python3
"""Apply the template's repository settings in the adoption run, as the Setup App.

.github/workflows/adopt.yml runs this after the branch symphony/adopt is
pushed and before the pull request opens, with the token of the OpenSpine
Symphony Setup App for the one repository (Administration: write, Metadata:
read), when the person installed that App on it. It does what the
template's scripts/setup-repo.sh does from a clone, through the REST API
with the standard library, so the repository's settings need no step by
hand:

  1. the ruleset of the template's docs/setup/ruleset-main.json for the
     default branch, unless the repository has one of that name already;
     in mode existing without the rule that requires the check named
     "check", which the template's own CI job carries and a repository
     the template did not make may not have, so that rule would hold
     its default branch to a check that never runs;
  2. "Automatically delete head branches" and "Allow auto-merge";
  3. secret scanning, then push protection, which GitHub accepts only
     once scanning is on; where the plan or the visibility offers
     neither, GitHub's answer is kept and the run goes on.

The labels are the workflow's, made with the main App's token; the
template's variables are optional and none is set here; the Claude token
is the person's own and never asked for; and GitHub's reading of
.github/CODEOWNERS is shown on the file's own page once it is merged.

  apply  does the above and writes a report of each setting's outcome. It
         exits 0 whatever GitHub answered, since the pull request is
         where the person reads what happened: GitHub's words go to the
         report, which scripts/adopt.py body --settings renders into the
         pull request in their repository, and this public log gets one
         fixed line per setting.
  skip   writes a report that says why nothing was applied: this front
         door has no Setup App yet; the App is not installed on the
         repository; the front door's own Setup App is not working, which
         a probe on the owner's installation tells from the first; or the
         step that applies them stopped before it could report. The pull
         request's text has one source for all of it.

Python 3.12 or later, standard library only. The token is read from
GH_TOKEN and never printed.
"""

import argparse
import http.client
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPORT_SCHEMA = "sdlc-setup/1"
API = "https://api.github.com"
API_VERSION = "2022-11-28"
USER_AGENT = "symphony-start-setup"
REPOSITORY = re.compile(r"[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}")
REQUIRED_CHECKS_RULE = "required_status_checks"

# A report's outcome: the settings were applied (each with its own state
# below), or nothing was, for one of two reasons.
APPLIED = "applied"
NOT_SET_UP = "not-set-up"
NOT_INSTALLED = "not-installed"
FRONT_DOOR_BROKEN = "front-door-broken"
NOT_REPORTED = "not-reported"
WHYS = (NOT_SET_UP, NOT_INSTALLED, FRONT_DOOR_BROKEN, NOT_REPORTED)
# One setting's state.
DONE = "done"
EXISTS = "exists"
FAILED = "failed"
NOT_TRIED = "not-tried"
# The settings, in the order they are applied and reported.
RULESET = "ruleset"
TOGGLES = "toggles"
SECRET_SCANNING = "secret_scanning"
PUSH_PROTECTION = "push_protection"
SETTINGS = (RULESET, TOGGLES, SECRET_SCANNING, PUSH_PROTECTION)
# GitHub's message lands in the pull request, so it is one line and short.
DETAIL_LENGTH = 300


class GitHubError(Exception):
    """GitHub said no, or could not be reached: one line that says which."""


def error_words(error):
    """One of GitHub's errors as words: its message, or, as a validation
    error is documented, its resource, field and code."""
    if isinstance(error, str):
        return error
    if not isinstance(error, dict):
        return ""
    if error.get("message"):
        return str(error["message"])
    return " ".join(str(error[key]) for key in ("resource", "field", "code") if error.get(key))


def github_message(data):
    """What GitHub's error body says, as one line: its message and each of
    its errors, where the body is JSON, else nothing."""
    try:
        body = json.loads(data)
    except (ValueError, TypeError):
        return ""
    if not isinstance(body, dict):
        return ""
    parts = [str(body.get("message") or "")] + [error_words(error) for error in body.get("errors") or []]
    return " ".join(" ".join(part.split()) for part in parts if part).strip()


def one_line(text, length=DETAIL_LENGTH):
    text = " ".join(str(text).split())
    return text if len(text) <= length else text[:length - 3].rstrip() + "..."


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is an answer, not a request to repeat: urllib would turn
    a redirected POST into a GET of the new place and report its 200, so
    every 3xx is handed back as the status it is."""

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def urllib_transport(method, url, headers, body):
    """(status, bytes) for one request; an HTTP error is an answer too, and
    only a failure to get one raises."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        try:
            with OPENER.open(request, timeout=30) as reply:
                return reply.status, reply.read()
        except urllib.error.HTTPError as error:
            # Reading the refusal's body can fail the same ways as the
            # request, so it stays inside the outer try.
            return error.code, error.read()
    except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
        raise GitHubError(f"GitHub could not be reached ({type(error).__name__})") from error


class GitHub:
    """The REST API with the token, through a transport the tests replace."""

    def __init__(self, token, transport=urllib_transport, api=API):
        self.token = token
        self.transport = transport
        self.api = api

    def call(self, method, path, body=None):
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": API_VERSION,
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        status, data = self.transport(method, f"{self.api}{path}", headers, body)
        if not 200 <= status < 300:
            said = github_message(data)
            raise GitHubError(f"HTTP {status}" + (f": {said}" if said else ""))
        try:
            return json.loads(data) if data and data.strip() else {}
        except ValueError:
            raise GitHubError(f"HTTP {status}: GitHub's answer was not JSON") from None


# --- the report -------------------------------------------------------------------


def new_report(outcome, mode):
    return {
        "schema": REPORT_SCHEMA,
        "outcome": outcome,
        "mode": mode,
        "private": None,
        "ruleset_name": None,
        "required_check": False,
        "settings": {},
    }


def record(report, key, state, detail=""):
    report["settings"][key] = {"state": state, "detail": one_line(detail) if detail else ""}


def write_report(path, report):
    Path(path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


# --- the settings -----------------------------------------------------------------


def ruleset_for(path, mode):
    """The template's ruleset as a dict; in mode existing without the rule
    that requires a check. ValueError when the file is not a ruleset."""
    ruleset = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(ruleset, dict) or not ruleset.get("name") or not isinstance(ruleset.get("rules"), list):
        raise ValueError("not a ruleset: no name or no list of rules")
    if mode == "existing":
        ruleset["rules"] = [rule for rule in ruleset["rules"] if rule.get("type") != REQUIRED_CHECKS_RULE]
    return ruleset


def requires_check(ruleset):
    return any(rule.get("type") == REQUIRED_CHECKS_RULE for rule in ruleset["rules"])


def read_visibility(github, repo, report):
    """Whether the repository is private, which the pull request's text
    needs: GitHub Free writes a private repository's ruleset but does not
    enforce it. The visibility, not the flag private, which an internal
    repository carries too. Unknown when the read fails; the settings are
    tried anyway."""
    try:
        report["private"] = github.call("GET", f"/repos/{repo}").get("visibility") == "private"
    except GitHubError:
        report["private"] = None


def apply_ruleset(github, repo, ruleset, report):
    """Create the ruleset unless the repository has one of that name. GitHub
    would make a second one of the same name, so the check is this script's.
    includes_parents=false keeps an organization's rulesets out of the
    list: they are not this repository's."""
    name = ruleset["name"]
    try:
        listed = github.call("GET", f"/repos/{repo}/rulesets?includes_parents=false")
        if any(isinstance(item, dict) and item.get("name") == name for item in listed):
            record(report, RULESET, EXISTS)
            return
        github.call("POST", f"/repos/{repo}/rulesets", ruleset)
        record(report, RULESET, DONE)
    except GitHubError as said:
        record(report, RULESET, FAILED, str(said))


def apply_toggles(github, repo, report):
    """The two toggles under General, one idempotent PATCH."""
    try:
        github.call("PATCH", f"/repos/{repo}", {"delete_branch_on_merge": True, "allow_auto_merge": True})
        record(report, TOGGLES, DONE)
    except GitHubError as said:
        record(report, TOGGLES, FAILED, str(said))


def apply_scanning(github, repo, report):
    """Secret scanning, then push protection, which GitHub accepts only once
    scanning is on. A refusal is the plan or the visibility, not the
    script: GitHub's words are kept for the pull request and the run goes
    on; push protection is not tried after scanning was refused."""
    try:
        github.call("PATCH", f"/repos/{repo}",
                    {"security_and_analysis": {"secret_scanning": {"status": "enabled"}}})
        record(report, SECRET_SCANNING, DONE)
    except GitHubError as said:
        record(report, SECRET_SCANNING, FAILED, str(said))
        record(report, PUSH_PROTECTION, NOT_TRIED, "secret scanning is not on")
        return
    try:
        github.call("PATCH", f"/repos/{repo}",
                    {"security_and_analysis": {"secret_scanning_push_protection": {"status": "enabled"}}})
        record(report, PUSH_PROTECTION, DONE)
    except GitHubError as said:
        record(report, PUSH_PROTECTION, FAILED, str(said))


def apply_settings(github, repo, ruleset, mode):
    """Every setting, each on its own: one that fails costs itself and
    nothing else. ruleset is the dict, or the one-line reason it could not
    be read."""
    report = new_report(APPLIED, mode)
    read_visibility(github, repo, report)
    if isinstance(ruleset, dict):
        report["ruleset_name"] = ruleset["name"]
        report["required_check"] = requires_check(ruleset)
        apply_ruleset(github, repo, ruleset, report)
    else:
        record(report, RULESET, FAILED, ruleset)
    apply_toggles(github, repo, report)
    apply_scanning(github, repo, report)
    return report


# The log is public: one fixed line per setting, never GitHub's words,
# which may name the plan, and never the repository's state beyond this.
LOG_LINES = {
    RULESET: {DONE: "ruleset: created", EXISTS: "ruleset: exists, left as it is", FAILED: "ruleset: not created"},
    TOGGLES: {DONE: "delete head branches on merge, allow auto-merge: on", FAILED: "the two toggles: not changed"},
    SECRET_SCANNING: {DONE: "secret scanning: on", FAILED: "secret scanning: not turned on"},
    PUSH_PROTECTION: {DONE: "push protection: on", FAILED: "push protection: not turned on",
                      NOT_TRIED: "push protection: not tried"},
}


def log_lines(report):
    for key in SETTINGS:
        setting = report["settings"].get(key)
        if setting:
            yield "settings: " + LOG_LINES[key][setting["state"]]


# --- the command line -------------------------------------------------------------


def command_apply(options, transport=urllib_transport):
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        print("setup: GH_TOKEN is not set", file=sys.stderr)
        return 2
    if not REPOSITORY.fullmatch(options.repo):
        print("setup: --repo must be OWNER/NAME", file=sys.stderr)
        return 2
    try:
        ruleset = ruleset_for(options.ruleset, options.mode)
    except (OSError, ValueError, UnicodeDecodeError):
        ruleset = "the template's ruleset file could not be read, so no ruleset was made"
    github = GitHub(token, transport, options.api)
    try:
        report = apply_settings(github, options.repo, ruleset, options.mode)
        write_report(options.report, report)
    except OSError as problem:
        print(f"setup: {problem}", file=sys.stderr)
        return 1
    for line in log_lines(report):
        print(line)
    return 0


def command_skip(options, transport=None):
    try:
        write_report(options.report, new_report(options.why, options.mode))
    except OSError as problem:
        print(f"setup: {problem}", file=sys.stderr)
        return 1
    print(f"settings: none applied ({options.why})")
    return 0


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Apply the template's repository settings as the Setup App.")
    commands = parser.add_subparsers(dest="command", required=True)

    applying = commands.add_parser("apply", help="apply the settings with the token in GH_TOKEN and write a report")
    applying.add_argument("--repo", required=True, help="the repository as OWNER/NAME")
    applying.add_argument("--ruleset", required=True, help="the template's docs/setup/ruleset-main.json")
    applying.add_argument("--mode", required=True, choices=("new", "existing"))
    applying.add_argument("--report", required=True, help="where to write the report")
    applying.add_argument("--api", default=API, help=argparse.SUPPRESS)

    skipping = commands.add_parser("skip", help="write a report that says why nothing was applied")
    skipping.add_argument("--why", required=True, choices=WHYS)
    skipping.add_argument("--mode", required=True, choices=("new", "existing"))
    skipping.add_argument("--report", required=True, help="where to write the report")
    return parser.parse_args(argv)


COMMANDS = {"apply": command_apply, "skip": command_skip}


def main(argv=None, transport=urllib_transport):
    options = parse_args(argv)
    return COMMANDS[options.command](options, transport)


if __name__ == "__main__":
    sys.exit(main())
