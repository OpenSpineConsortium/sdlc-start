#!/usr/bin/env python3
"""Find the repositories the App is installed on that have no adoption yet.

Installing the OpenSpine SDLC App on a repository is the request: GitHub
tells only a webhook about an installation, and no workflow runs on one,
so .github/workflows/sweep.yml runs this on a schedule instead. With the
App's JWT (scripts/jwt.sh) it reads the App's own record, for the login of
its bot, and lists the App's installations; then it mints each
installation's token, lists the repositories that token reaches and keeps
the ones with no adoption yet; the workflow starts one adoption run per
line of the file this writes.

An installation is passed over whole, with no token made for it, and the
log counts it, when it is

  permissions  short of what the adoption run needs (contents, issues,
               pull requests and workflows as write; a permission the
               owner has not accepted yet is missing here), since every
               run on its repositories would fail at the token, ten
               minutes apart;
  fresh        younger than --grace-minutes (30 by default), by its
               updated_at or, failing that, its created_at: the form is
               answered within a minute and this sweep is not, so a
               person who installs the App and then fills in the form
               within that time keeps the choices the form takes;
  unreadable   one whose token or list of repositories could not be had;
  deferred     not reached, or not finished, when the budget (below) ran
               out; the next sweep takes it up.

A repository is left out, each reason counted, when

  own         its owner is the organization's own (--own): the template,
              this front door and the rest take no adoption of themselves;
  archived    GitHub refuses every push to it;
  no issues   its Issues are off (a fork's are, by default): the run on
              this path tells the repository in an issue when it could not
              open the pull request, and mode new opens one, so a
              repository that takes none is left to the form;
  pending     it is named, OWNER/NAME in any case, on a line of the file
              --pending or under the heading "### Repository" of an issue
              in the file --requests (the open requests of the form, as
              gh issue list --json body writes them), so the form's run
              has it;
  no commit   its default branch is not there yet, so there is nothing to
              branch from; the README says a README is enough;
  offered     the branch sdlc/adopt is there: an adoption was offered, and
              its pull request is open, merged, or closed on purpose;
  adopted     docs/agents/PROTOCOL.md is on its default branch, by the form
              or by "Use this template";
  opted out   .github/sdlc-adopt on its default branch says off: the App is
              wanted for the metrics alone;
  declined    a pull request from sdlc/adopt was closed and the branch is
              gone since: the offer was declined, and is not made again;
  refused     an issue titled "OpenSpine SDLC could not open its pull
              request" (REFUSAL_TITLE) is open, opened by the App's bot:
              the adoption run on this path could not push its branch,
              the repository's rules having refused it, and said so there
              once rather than fail every ten minutes; closing that issue,
              once the rules allow the push, arms the sweep again;
  unreadable  one of those checks got an answer that was neither yes nor a
              clean 404, so the next sweep looks again.

Without a form, the mode is read from the tree: a default branch holding
nothing but what GitHub's "initialize this repository" makes (a README, a
LICENSE or COPYING, .gitignore, .gitattributes) is new, and anything else
is existing, which overwrites nothing. The requester is not chosen here:
the adoption run picks one once it holds the repository's token.

The run is bounded in time: --budget-seconds (420 by default, under the
JWT's nine minutes and the job's ten) from the start, after which no
installation and no repository is taken up, what is left is counted as
deferred, the summary says the run was cut short, and the exit is still 0.
So that one installation too large for a budget cannot hold the first
slot every time, the installations are swept from a starting point that
moves one along every ten minutes, the sweep's period, and around to the
start; the repositories of an installation keep GitHub's order. Each
candidate goes to the file --out as it is found, one line
installation_id<TAB>repository_id<TAB>mode, in the order found and flushed
at once, so a run cut short has written what it found.

The workflow's log is public, so stdout carries counts and nothing else: no
repository, owner or login. Exit 1 when the App's record or its
installations could not be read, with GitHub's status and message on
stderr, which name no repository, and no file written; exit 2 when APP_JWT
is not set or the file --pending or --requests cannot be read. Python
3.12 or later,
standard library only. The JWT is read from APP_JWT and never printed;
each installation's token lives for that installation's repositories and
is revoked afterwards.
"""

import argparse
import base64
import collections
import datetime
import http.client
import json
import os
import re
import sys
import time
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
ADOPT_BRANCH = "sdlc/adopt"
PROTOCOL_TEXT = "docs/agents/PROTOCOL.md"
OPT_OUT = ".github/sdlc-adopt"
# The form's label for the repository, a heading of the issue's body.
REPOSITORY_HEADING = "### Repository"
NO_RESPONSE = "_No response_"
# The title of the issue the adoption run opens, as the App, when the
# repository's rules refused its push; .github/workflows/adopt-run.yml
# uses the same words, and the sweep skips the repository while it is open.
REFUSAL_TITLE = "OpenSpine SDLC could not open its pull request"
GRACE_MINUTES = 30
BUDGET_SECONDS = 420
# The workflow's schedule: the starting installation moves along with it.
SWEEP_PERIOD = 600
# What the adoption run asks the App's token for, as write; metadata read
# comes with them.
NEEDED_PERMISSIONS = ("contents", "issues", "pull_requests", "workflows")
# What GitHub's "initialize this repository" makes, by the name's stem
# (README.md, LICENSE.txt, COPYING) or by the whole name.
INIT_STEMS = ("readme", "license", "copying")
INIT_NAMES = (".gitignore", ".gitattributes")
# The reasons the log counts, as words; the pull request never sees them.
PERMISSIONS = "permissions"
FRESH = "fresh"
DEFERRED = "deferred"
OWN_REASON = "own"
ARCHIVED = "archived"
NO_ISSUES = "no issues"
PENDING = "pending"
NO_COMMIT = "no commit"
OFFERED = "offered"
ADOPTED = "adopted"
OPTED_OUT = "opted out"
DECLINED = "declined"
REFUSED = "refused"
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

    def listed(self, path):
        """The one page of a list at this path; an answer that is not a
        list says nothing, so it is a refusal."""
        answer = self.call("GET", path)
        if not isinstance(answer, list):
            raise GitHubError("GitHub's answer was not a list")
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


def bot_login(app):
    """The login the App's own issues carry, <slug>[bot], from the App's
    record; a record with no slug is a refusal, since without the login
    the refused check cannot be made."""
    answer = app.call("GET", "/app")
    slug = answer.get("slug") if isinstance(answer, dict) else None
    if not slug or not isinstance(slug, str):
        raise GitHubError("GitHub's answer held no slug")
    return f"{slug}[bot]"


def list_installations(app):
    return app.pages(f"/app/installations?per_page={PER_PAGE}")


def prepare(app):
    """(the bot's login, the installations), both from the App's own
    endpoints, before any token is minted; a failure of either is raised
    with words that say which, since then nothing was swept."""
    try:
        bot = bot_login(app)
    except GitHubError as refusal:
        raise GitHubError(f"the App could not be read ({refusal})", refusal.status) from refusal
    try:
        return bot, list(list_installations(app))
    except GitHubError as refusal:
        raise GitHubError(f"the installations could not be listed ({refusal})", refusal.status) from refusal


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


def changed_at(installation):
    """When the installation last changed, as seconds since the epoch: its
    updated_at, or its created_at when that is missing or not a date; None
    when neither reads as one, which GitHub never sends. The dates come
    as ISO 8601 with Z, and one with no zone is taken as UTC."""
    for key in ("updated_at", "created_at"):
        value = installation.get(key)
        if not isinstance(value, str):
            continue
        try:
            moment = datetime.datetime.fromisoformat(value)
        except ValueError:
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=datetime.timezone.utc)
        return moment.timestamp()
    return None


def is_fresh(installation, now, grace):
    """Whether the installation is younger than the grace, in seconds, so
    the form may still be on its way for it."""
    moment = changed_at(installation)
    return moment is not None and now - moment < grace


def rotated(installations, now):
    """The installations from a starting slot that moves one along every
    sweep period and around to the start again: an installation too large
    for one budget then holds the first slot one sweep in n, not every
    sweep."""
    if not installations:
        return []
    start = int(now // SWEEP_PERIOD) % len(installations)
    return installations[start:] + installations[:start]


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
    refs = github.listed(f"/repos/{repository['full_name']}/git/matching-refs/heads/{ADOPT_BRANCH}")
    return any(isinstance(ref, dict) and ref.get("ref") == ADOPT_REF for ref in refs)


def is_adopted(github, repository):
    return found(github, f"/repos/{repository['full_name']}/contents/{PROTOCOL_TEXT}")


def switch_word(answer):
    """The one word a contents answer holds, stripped and lower-cased, or
    nothing when the answer is not a base64 file (a folder, a file too
    large to come inline, bytes that are not text). An editor's byte order
    mark is not part of the word."""
    if not isinstance(answer, dict) or answer.get("encoding") != "base64":
        return ""
    try:
        return base64.b64decode(answer.get("content") or "").decode("utf-8-sig").strip().lower()
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


def was_declined(github, repository):
    """Whether a pull request from sdlc/adopt was closed. By the time this
    is asked the branch is gone (else the repository read as offered) and
    the pull request was not merged (else as adopted), so the offer was
    closed on purpose; one such pull request is enough to know."""
    owner = repository["owner"]["login"]
    path = f"/repos/{repository['full_name']}/pulls?state=closed&head={owner}:{ADOPT_BRANCH}&per_page=1"
    return bool(github.listed(path))


def is_refusal(issue):
    """The App's refusal issue by its exact title; the issues list holds
    pull requests too, told by the key they alone carry."""
    return isinstance(issue, dict) and issue.get("title") == REFUSAL_TITLE and "pull_request" not in issue


def was_refused(github, repository, bot):
    """Whether the issue the adoption run opened, when the repository's
    rules refused its push, is still open. The run opens it once, so one
    page of the bot's open issues holds it."""
    creator = urllib.parse.quote(bot, safe="")
    path = f"/repos/{repository['full_name']}/issues?state=open&creator={creator}&per_page={PER_PAGE}"
    return any(is_refusal(issue) for issue in github.listed(path))


class Settings(NamedTuple):
    """What the command line decides: whose repositories are never
    candidates; which are the form's, as lower-cased OWNER/NAME; how young
    an installation is left alone, in seconds; how long the run may take,
    in seconds."""
    own: str
    pending: frozenset
    grace: float
    budget: float


def why_skipped(github, repository, settings, bot):
    """The reason this repository is no candidate, or None. The checks that
    need no call come first, then the ones that read the branches and the
    files, then the ones that read what an earlier offer left behind (a
    closed pull request, an open issue); the opt-out comes before those
    two because it is the person's own word and costs one call. A
    GitHubError from any of them is the caller's."""
    if repository["owner"]["login"].lower() == settings.own.lower():
        return OWN_REASON
    if repository.get("archived"):
        return ARCHIVED
    if not repository.get("has_issues", True):
        return NO_ISSUES
    if repository["full_name"].lower() in settings.pending:
        return PENDING
    if not has_commit(github, repository):
        return NO_COMMIT
    if has_adopt_branch(github, repository):
        return OFFERED
    if is_adopted(github, repository):
        return ADOPTED
    if opted_out(github, repository):
        return OPTED_OUT
    if was_declined(github, repository):
        return DECLINED
    if was_refused(github, repository, bot):
        return REFUSED
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


def consider(github, repository, installation_id, settings, bot, tally):
    """The candidate this repository makes, or None once its reason is
    counted. A refusal that is not a clean 404, on any check or on the
    tree, is unreadable: the mode must not be guessed, since mode new
    replaces files, and the next sweep looks again."""
    tally.repositories += 1
    try:
        reason = why_skipped(github, repository, settings, bot)
        mode = None if reason else classify_tree(read_tree(github, repository))
    except GitHubError:
        reason = UNREADABLE
    if reason:
        tally.skipped[reason] += 1
        return None
    tally.candidates += 1
    return Candidate(installation_id, repository["id"], mode)


class Sweep:
    """One run across the App's installations: the App's client, its bot's
    login, the settings, the clock and the moment the budget is spent,
    and the counts the log prints. Every candidate goes to keep as it is
    found."""

    def __init__(self, app, bot, settings, now, started):
        self.app = app
        self.bot = bot
        self.settings = settings
        self.now = now
        self.deadline = started + settings.budget
        self.tally = Tally()

    def spent(self):
        return self.now() >= self.deadline

    def run(self, installations, keep):
        """The counts, once every installation was swept, passed over or
        deferred: the ones the budget never reached are deferred together."""
        self.tally.installations = len(installations)
        for position, installation in enumerate(rotated(installations, self.now())):
            if self.spent():
                self.tally.passed_over[DEFERRED] += len(installations) - position
                break
            self.sweep_installation(installation, keep)
        return self.tally

    def sweep_installation(self, installation, keep):
        """One installation, counted when it is passed over: short of
        permissions or fresh before any token is minted, unreadable when
        its token or its list cannot be had, deferred when the budget ran
        out among its repositories."""
        passed_over = self.tally.passed_over
        if not has_permissions(installation):
            passed_over[PERMISSIONS] += 1
        elif is_fresh(installation, self.now(), self.settings.grace):
            passed_over[FRESH] += 1
        else:
            try:
                if not self.sweep_repositories(installation["id"], keep):
                    passed_over[DEFERRED] += 1
            except GitHubError:
                passed_over[UNREADABLE] += 1

    def sweep_repositories(self, installation_id, keep):
        """True once every repository of the installation was considered,
        False when the budget ran out first; the token lives for this call
        and is revoked on the way out, whatever happened."""
        github = self.app.with_token(installation_token(self.app, installation_id))
        try:
            for repository in list_repositories(github):
                if self.spent():
                    return False
                candidate = consider(github, repository, installation_id, self.settings, self.bot, self.tally)
                if candidate:
                    keep(candidate)
            return True
        finally:
            revoke(github)


# --- the output -------------------------------------------------------------------


def write_candidate(handle, candidate):
    """One line, flushed at once, so a run cut short has written what it
    found by then."""
    handle.write(f"{candidate.installation}\t{candidate.repository}\t{candidate.mode}\n")
    handle.flush()


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
    line += f" ({reasons})" if reasons else ""
    if tally.passed_over[DEFERRED]:
        line += ", cut short by the budget"
    return line


# --- the command line -------------------------------------------------------------


def parse_args(argv):
    parser = argparse.ArgumentParser(description="List the App's installations and find the repositories to adopt.")
    parser.add_argument("--own", default=OWN, help="the organization whose own repositories are never candidates")
    parser.add_argument("--out", required=True, help="where to write the candidates, one per line as TSV")
    parser.add_argument("--pending", metavar="PATH",
                        help="a file naming, OWNER/NAME per line, the repositories of the requests still open on the "
                             "form, which are left to them")
    parser.add_argument("--requests", metavar="PATH",
                        help="the open requests of the form as gh issue list --json body writes them; the repository "
                             "each names is left to it")
    parser.add_argument("--grace-minutes", type=float, default=GRACE_MINUTES,
                        help="leave an installation younger than this alone, so the form may still speak for it "
                             f"(default {GRACE_MINUTES})")
    parser.add_argument("--budget-seconds", type=float, default=BUDGET_SECONDS,
                        help=f"take up no installation and no repository this long into the run (default {BUDGET_SECONDS})")
    parser.add_argument("--api", default=API, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def read_pending(path):
    """The repositories the file names, each line stripped and lower-cased,
    since a full name compares without case; none without a file."""
    if not path:
        return frozenset()
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return frozenset(line.strip().lower() for line in lines if line.strip())


def named_repository(body):
    """The repository an issue of the form names: the first line under the
    heading "### Repository", before the next heading; nothing when the
    field was left empty, which GitHub writes as _No response_."""
    under = False
    for line in body.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        word = line.strip()
        if word == REPOSITORY_HEADING:
            under = True
        elif under and word.startswith("### "):
            return ""
        elif under and word and word != NO_RESPONSE:
            return word.lower()
    return ""


def read_requests(path):
    """The repositories the open requests name, from the JSON list of
    issues with a body that gh issue list --json body writes; a file that
    is not that is an OSError, like one that is not there."""
    if not path:
        return frozenset()
    try:
        issues = json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError as problem:
        raise OSError(f"{path} is not the JSON gh issue list writes ({problem})") from problem
    if not isinstance(issues, list):
        raise OSError(f"{path} is not the JSON gh issue list writes (not a list)")
    named = (named_repository(str(issue.get("body") or "")) for issue in issues if isinstance(issue, dict))
    return frozenset(name for name in named if name)


def settings_from(options):
    pending = read_pending(options.pending) | read_requests(options.requests)
    return Settings(options.own, pending, options.grace_minutes * 60, options.budget_seconds)


def main(argv=None, transport=urllib_transport, now=time.time):
    options = parse_args(argv)
    started = now()
    jwt = os.environ.get("APP_JWT", "")
    if not jwt:
        print("sweep: APP_JWT is not set", file=sys.stderr)
        return 2
    try:
        settings = settings_from(options)
    except OSError as problem:
        print(f"sweep: {problem}", file=sys.stderr)
        return 2
    app = GitHub(jwt, transport, options.api)
    try:
        bot, installations = prepare(app)
    except GitHubError as refusal:
        print(f"sweep: {refusal}", file=sys.stderr)
        return 1
    try:
        with open(options.out, "w", encoding="utf-8") as handle:
            run = Sweep(app, bot, settings, now, started)
            tally = run.run(installations, lambda candidate: write_candidate(handle, candidate))
    except OSError as problem:
        print(f"sweep: {problem}", file=sys.stderr)
        return 1
    print(summary(tally))
    return 0


if __name__ == "__main__":
    sys.exit(main())
