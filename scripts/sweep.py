#!/usr/bin/env python3
"""Find the repositories the App is installed on that have no adoption yet.

Installing the OpenSpine SDLC App on a repository is the request: GitHub
tells only a webhook about an installation, and no workflow runs on one,
so .github/workflows/sweep.yml runs this on a schedule instead. With the
App's JWT (scripts/jwt.sh) it lists the App's installations, mints each
one's token, lists the repositories that token reaches and keeps the ones
with no adoption yet; the workflow starts one adoption run per line of the
file this writes. An installation is passed over whole, with no token made
for it, when its permissions do not let the adoption run do its work
(contents, issues, pull requests and workflows as write; a permission the
owner has not accepted yet is missing here), since every run on its
repositories would fail at the token, ten minutes apart; the log counts it
as permissions, and as unreadable when its token or its list could not be
had. A repository is left out, each reason counted, when

  own         its owner is the organization's own (--own): the template,
              this front door and the rest take no adoption of themselves;
  archived    GitHub refuses every push to it;
  no commit   its default branch is not there yet, so there is nothing to
              branch from; the README says a README is enough;
  offered     the branch sdlc/adopt is there: an adoption was offered, and
              its pull request is open, merged, or closed on purpose;
  adopted     docs/agents/PROTOCOL.md is on its default branch, by the form
              or by "Use this template";
  opted out   .github/sdlc-adopt on its default branch says off: the App is
              wanted for the metrics alone;
  unreadable  one of those checks got an answer that was neither yes nor a
              clean 404, so the next sweep looks again.

Without a form, the mode is read from the tree: a default branch holding
nothing but what GitHub's "initialize this repository" makes (a README, a
LICENSE or COPYING, .gitignore, .gitattributes) is new, and anything else
is existing, which overwrites nothing. The requester is not chosen here:
the adoption run picks one once it holds the repository's token.

The workflow's log is public, so stdout carries counts and nothing else: no
repository, owner or login. The candidates go to the file --out as
installation_id<TAB>repository_id<TAB>mode, sorted, written once at the
end. Exit 1 when the installations could not be listed at all, with
GitHub's status and message on stderr, which name no repository. Python
3.12 or later, standard library only. The JWT is read from APP_JWT and
never printed; each installation's token lives for that installation's
repositories and is revoked afterwards.
"""

import argparse
import base64
import collections
import http.client
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import NamedTuple

API = "https://api.github.com"
API_VERSION = "2022-11-28"
USER_AGENT = "sdlc-start-sweep"
OWN = "OpenSpineConsortium"
PER_PAGE = 100
ADOPT_REF = "refs/heads/sdlc/adopt"
PROTOCOL_TEXT = "docs/agents/PROTOCOL.md"
OPT_OUT = ".github/sdlc-adopt"
# What the adoption run asks the App's token for, as write; metadata read
# comes with them.
NEEDED_PERMISSIONS = ("contents", "issues", "pull_requests", "workflows")
# What GitHub's "initialize this repository" makes, by the name's stem
# (README.md, LICENSE.txt, COPYING) or by the whole name.
INIT_STEMS = ("readme", "license", "copying")
INIT_NAMES = (".gitignore", ".gitattributes")
# The reasons the log counts, as words; the pull request never sees them.
PERMISSIONS = "permissions"
OWN_REASON = "own"
ARCHIVED = "archived"
NO_COMMIT = "no commit"
OFFERED = "offered"
ADOPTED = "adopted"
OPTED_OUT = "opted out"
UNREADABLE = "unreadable"
NEW = "new"
EXISTING = "existing"
LINK = re.compile(r'<([^>]+)>;\s*rel="([^"]+)"')


class GitHubError(Exception):
    """GitHub said no, or could not be reached: one line that says which,
    and the HTTP status when there was one, since a 404 is often the
    answer and not a failure."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


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


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is an answer, not a request to repeat: urllib would turn
    a redirected POST into a GET of the new place and report its 200, so
    every 3xx is handed back as the status it is."""

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def urllib_transport(method, url, headers, body):
    """(status, reply headers, bytes) for one request; an HTTP error is an
    answer too, and only a failure to get one raises. The reply's headers
    come along because the Link header carries the next page."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        try:
            with OPENER.open(request, timeout=30) as reply:
                return reply.status, dict(reply.headers.items()), reply.read()
        except urllib.error.HTTPError as error:
            # Reading the refusal's body can fail the same ways as the
            # request, so it stays inside the outer try.
            return error.code, dict(error.headers.items()), error.read()
    except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
        raise GitHubError(f"GitHub could not be reached ({type(error).__name__})") from error


def next_page(link):
    """The URL the Link header marks rel="next", or None at the last page."""
    for url, rel in LINK.findall(link or ""):
        if rel == "next":
            return url
    return None


class GitHub:
    """The REST API with one token, through a transport the tests replace.
    The sweep holds two of these on the same transport: the App's, whose
    token is the JWT, and one per installation."""

    def __init__(self, token, transport=urllib_transport, api=API):
        self.token = token
        self.transport = transport
        self.api = api

    def with_token(self, token):
        return GitHub(token, self.transport, self.api)

    def request(self, method, url, body=None):
        """(the answer as JSON, the reply's headers lower-cased); a non-2xx
        status is a GitHubError that keeps the status."""
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": API_VERSION,
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        status, replied, data = self.transport(method, url, headers, body)
        if not 200 <= status < 300:
            said = github_message(data)
            raise GitHubError(f"HTTP {status}" + (f": {said}" if said else ""), status)
        try:
            answer = json.loads(data) if data and data.strip() else {}
        except ValueError:
            raise GitHubError(f"HTTP {status}: GitHub's answer was not JSON", status) from None
        return answer, {name.lower(): value for name, value in replied.items()}

    def call(self, method, path, body=None):
        answer, _ = self.request(method, f"{self.api}{path}", body)
        return answer

    def pages(self, path, key=None):
        """Every item of a paginated list, page after page as the Link header
        points, until there is no next page. A next page outside the API
        is not followed, since the token would go with it, and a page seen
        twice ends the walk rather than repeating it."""
        url, seen = f"{self.api}{path}", set()
        while url and url not in seen:
            seen.add(url)
            answer, headers = self.request("GET", url)
            items = answer.get(key) if key and isinstance(answer, dict) else answer
            if not isinstance(items, list):
                raise GitHubError("GitHub's answer was not a list")
            yield from items
            url = next_page(headers.get("link"))
            if url and not url.startswith(f"{self.api}/"):
                url = None


# --- the App and its installations ------------------------------------------------


def list_installations(app):
    return app.pages(f"/app/installations?per_page={PER_PAGE}")


def has_permissions(installation):
    """Whether the installation's token could do what the adoption run does:
    push a branch with workflow files, open a pull request and an issue.
    The permissions an installation carries are the ones its owner
    accepted, so one added to the App since shows here only once the
    owner has reviewed it."""
    permissions = installation.get("permissions") if isinstance(installation, dict) else None
    if not isinstance(permissions, dict):
        return False
    return all(permissions.get(name) == "write" for name in NEEDED_PERMISSIONS)


def installation_token(app, installation_id):
    """A token for the whole installation with the App's default
    permissions: the body {} asks for every repository it reaches."""
    answer = app.call("POST", f"/app/installations/{installation_id}/access_tokens", {})
    token = answer.get("token") if isinstance(answer, dict) else None
    if not token:
        raise GitHubError("GitHub's answer held no token")
    return token


def list_repositories(github):
    return list(github.pages(f"/installation/repositories?per_page={PER_PAGE}", key="repositories"))


def revoke(github):
    """The installation's token is good for an hour; it is not needed past
    this sweep, and a failure to revoke it costs nothing but that hour."""
    try:
        github.call("DELETE", "/installation/token")
    except GitHubError:
        pass


# --- one repository ---------------------------------------------------------------


def found(github, path):
    """True when GitHub answers the GET, False on a clean 404; any other
    refusal is raised, since it says nothing about the repository."""
    try:
        github.call("GET", path)
        return True
    except GitHubError as refusal:
        if refusal.status == 404:
            return False
        raise


def branch_path(repository):
    return urllib.parse.quote(repository["default_branch"], safe="")


def has_commit(github, repository):
    """A repository with no commit has a default branch in name only: the
    branch itself answers 404."""
    return found(github, f"/repos/{repository['full_name']}/branches/{branch_path(repository)}")


def has_adopt_branch(github, repository):
    """matching-refs matches by prefix, so the ref is checked to be exactly
    sdlc/adopt and not a branch that merely starts so."""
    refs = github.call("GET", f"/repos/{repository['full_name']}/git/matching-refs/heads/sdlc/adopt")
    return any(isinstance(ref, dict) and ref.get("ref") == ADOPT_REF for ref in refs or [])


def is_adopted(github, repository):
    return found(github, f"/repos/{repository['full_name']}/contents/{PROTOCOL_TEXT}")


def switch_word(answer):
    """The one word a contents answer holds, stripped and lower-cased, or
    nothing when the answer is not a base64 file (a folder, a file too
    large to come inline, bytes that are not text)."""
    if not isinstance(answer, dict) or answer.get("encoding") != "base64":
        return ""
    try:
        return base64.b64decode(answer.get("content") or "").decode("utf-8").strip().lower()
    except (ValueError, UnicodeDecodeError):
        return ""


def opted_out(github, repository):
    try:
        answer = github.call("GET", f"/repos/{repository['full_name']}/contents/{OPT_OUT}")
    except GitHubError as refusal:
        if refusal.status == 404:
            return False
        raise
    return switch_word(answer) == "off"


def why_skipped(github, repository, own):
    """The reason this repository is no candidate, or None. The checks that
    need no call come first, then the ones that read the branches, then the
    ones that read files; a GitHubError from any of them is the caller's."""
    if repository["owner"]["login"].lower() == own.lower():
        return OWN_REASON
    if repository.get("archived"):
        return ARCHIVED
    if not has_commit(github, repository):
        return NO_COMMIT
    if has_adopt_branch(github, repository):
        return OFFERED
    if is_adopted(github, repository):
        return ADOPTED
    if opted_out(github, repository):
        return OPTED_OUT
    return None


def is_init_file(path):
    """Whether GitHub's "initialize this repository" could have made this
    file: at the top of the tree, a README or a LICENSE or COPYING under
    any extension or none, .gitignore or .gitattributes, whatever the case."""
    if "/" in path:
        return False
    name = path.lower()
    return name in INIT_NAMES or name.split(".", 1)[0] in INIT_STEMS


def classify_tree(tree):
    """new when every file of the tree is one GitHub's initialization makes,
    so the template may replace them; existing otherwise, and also when
    GitHub cut the listing short, since an unseen file is not known to be
    harmless. Folders are not files; a submodule or anything else that is
    not a blob is a file of the repository's own."""
    if not isinstance(tree, dict) or tree.get("truncated") or not isinstance(tree.get("tree"), list):
        return EXISTING
    for entry in tree["tree"]:
        if not isinstance(entry, dict) or entry.get("type") == "tree":
            continue
        if entry.get("type") != "blob" or not is_init_file(str(entry.get("path", ""))):
            return EXISTING
    return NEW


def read_tree(github, repository):
    return github.call("GET", f"/repos/{repository['full_name']}/git/trees/{branch_path(repository)}?recursive=1")


class Candidate(NamedTuple):
    installation: int
    repository: int
    mode: str


class Tally:
    """The counts the public log prints: never a name."""

    def __init__(self):
        self.installations = 0
        self.passed_over = collections.Counter()
        self.repositories = 0
        self.candidates = 0
        self.skipped = collections.Counter()


def consider(github, repository, installation_id, own, tally):
    """The candidate this repository makes, or None once its reason is
    counted. A refusal that is not a clean 404, on any check or on the
    tree, is unreadable: the mode must not be guessed, since mode new
    replaces files, and the next sweep looks again."""
    tally.repositories += 1
    try:
        reason = why_skipped(github, repository, own)
        mode = None if reason else classify_tree(read_tree(github, repository))
    except GitHubError:
        reason = UNREADABLE
    if reason:
        tally.skipped[reason] += 1
        return None
    tally.candidates += 1
    return Candidate(installation_id, repository["id"], mode)


def sweep_installation(app, installation_id, own, tally):
    """The candidates among one installation's repositories; its token
    lives for this call and is revoked on the way out, whatever happened."""
    github = app.with_token(installation_token(app, installation_id))
    try:
        candidates = []
        for repository in list_repositories(github):
            candidate = consider(github, repository, installation_id, own, tally)
            if candidate:
                candidates.append(candidate)
        return candidates
    finally:
        revoke(github)


def sweep(app, own):
    """Every candidate across the App's installations, with the counts. An
    installation short of permissions, or whose token cannot be made or
    whose repositories cannot be listed, is counted and passed over; a
    failure to list the installations themselves is raised, since then
    nothing was swept."""
    tally, candidates = Tally(), []
    for installation in list_installations(app):
        tally.installations += 1
        if not has_permissions(installation):
            tally.passed_over[PERMISSIONS] += 1
            continue
        try:
            candidates.extend(sweep_installation(app, installation["id"], own, tally))
        except GitHubError:
            tally.passed_over[UNREADABLE] += 1
    return candidates, tally


# --- the output -------------------------------------------------------------------


def write_candidates(path, candidates):
    lines = [f"{found.installation}\t{found.repository}\t{found.mode}\n" for found in sorted(candidates)]
    Path(path).write_text("".join(lines), encoding="utf-8")


def counted(count, one, many):
    return f"{count} {one if count == 1 else many}"


def summary(tally):
    installations = counted(tally.installations, "installation", "installations")
    if tally.passed_over:
        passed = ", ".join(f"{count} {reason}" for reason, count in sorted(tally.passed_over.items()))
        installations += f" ({passed})"
    line = (f"sweep: {installations}, {counted(tally.repositories, 'repository', 'repositories')}, "
            f"{counted(tally.candidates, 'candidate', 'candidates')}, {sum(tally.skipped.values())} skipped")
    reasons = ", ".join(f"{count} {reason}" for reason, count in sorted(tally.skipped.items()))
    return line + (f" ({reasons})" if reasons else "")


# --- the command line -------------------------------------------------------------


def parse_args(argv):
    parser = argparse.ArgumentParser(description="List the App's installations and find the repositories to adopt.")
    parser.add_argument("--own", default=OWN, help="the organization whose own repositories are never candidates")
    parser.add_argument("--out", required=True, help="where to write the candidates, one per line as TSV")
    parser.add_argument("--api", default=API, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv=None, transport=urllib_transport):
    options = parse_args(argv)
    jwt = os.environ.get("APP_JWT", "")
    if not jwt:
        print("sweep: APP_JWT is not set", file=sys.stderr)
        return 2
    try:
        candidates, tally = sweep(GitHub(jwt, transport, options.api), options.own)
    except GitHubError as refusal:
        print(f"sweep: the installations could not be listed ({refusal})", file=sys.stderr)
        return 1
    try:
        write_candidates(options.out, candidates)
    except OSError as problem:
        print(f"sweep: {problem}", file=sys.stderr)
        return 1
    print(summary(tally))
    return 0


if __name__ == "__main__":
    sys.exit(main())
