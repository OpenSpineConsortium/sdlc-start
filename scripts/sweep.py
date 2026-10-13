#!/usr/bin/env python3
"""The GitHub client and the adoption rules the front door's paths share.

The sweep that gave this file its name is gone: installing the App is no
longer a request by itself, since the install's redirect lands on the form,
where one press of Create is the request. What stays is what the form's
two paths import: a REST client on one token, through a transport the
tests replace (GitHub, GitHubError, urllib_transport); the rule for a
repository with no adoption yet, which scripts/resolve.py asks of each
repository an installation reaches (unadopted, with the checks it makes:
a commit, no branch symphony/adopt, no docs/agents/PROTOCOL.md, no
opt-out, or no commit at all, an empty repository, whose first commit the
run makes); the one check scripts/adopted.py asks of a repository named on
the form (is_adopted); and the reading of the kind from a tree that
.github/workflows/adopt-run.yml asks when the form left the kind to the
run (classify_tree). Python 3.12 or later, standard library only.
"""

import base64
import datetime
import http.client
import json
import re
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
API_VERSION = "2022-11-28"
USER_AGENT = "symphony-start"
PER_PAGE = 100
ADOPT_REF = "refs/heads/symphony/adopt"
ADOPT_BRANCH = "symphony/adopt"
# The names before the rename to Symphony, still read, since a repository
# adopted before it carries them.
OLD_ADOPT_REF = "refs/heads/sdlc/adopt"
OLD_ADOPT_BRANCH = "sdlc/adopt"
OLD_OPT_OUT = ".github/sdlc-adopt"
PROTOCOL_TEXT = "docs/agents/PROTOCOL.md"
OPT_OUT = ".github/symphony-adopt"
# What GitHub's "initialize this repository" makes, by the name's stem
# (README.md, LICENSE.txt, COPYING) or by the whole name.
INIT_STEMS = ("readme", "license", "copying")
INIT_NAMES = (".gitignore", ".gitattributes")
NEW = "new"
EXISTING = "existing"
# The status of some of GitHub's answers about a repository with no
# commit: "Git Repository is empty".
EMPTY_STATUS = 409
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
    scripts/resolve.py holds two of these on the same transport: the App's,
    whose token is the JWT, and the installation's."""

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


def revoke(github):
    """The installation's token is good for an hour; it is not needed past
    the run that minted it, and a failure to revoke it costs nothing but
    that hour."""
    try:
        github.call("DELETE", "/installation/token")
    except GitHubError:
        pass


# --- one repository ---------------------------------------------------------------


def repo_path(repository):
    """The repository's place in the API: by name, or by id when the dict
    says so (by_id), for a caller that holds the id and must not learn the
    name, as the form's workflow does before anything is masked."""
    if repository.get("by_id"):
        return f"/repositories/{repository['id']}"
    return f"/repos/{repository['full_name']}"


def unadopted(github, repositories):
    """The repositories among these with no adoption yet: those with a
    commit and no branch symphony/adopt, no docs/agents/PROTOCOL.md and no
    opt-out, and those with no commit at all, whose first commit the form's
    run makes. The form's workflow asks this of an installation that
    reaches several, to find the one the person meant; a GitHubError is the
    caller's."""
    free = []
    for repository in repositories:
        if repository.get("archived"):
            continue
        if not has_commit(github, repository):
            if is_empty(github, repository):
                free.append(repository)
            continue
        if has_adopt_branch(github, repository) or is_adopted(github, repository) or opted_out(github, repository):
            continue
        free.append(repository)
    return free


def created_at(repository):
    """When the repository was created, as seconds since the epoch, or 0
    when GitHub's answer holds no date that reads."""
    value = repository.get("created_at")
    if not isinstance(value, str):
        return 0.0
    try:
        moment = datetime.datetime.fromisoformat(value)
    except ValueError:
        return 0.0
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return moment.timestamp()


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
    branch itself answers 404, or 409 where GitHub says the repository is
    empty."""
    try:
        return found(github, f"{repo_path(repository)}/branches/{branch_path(repository)}")
    except GitHubError as refusal:
        if refusal.status == EMPTY_STATUS:
            return False
        raise


def is_empty(github, repository):
    """Whether the repository has no branch at all, so no commit: an empty
    one, whose first commit the form's run makes, as against a default
    branch missing beside branches of the repository's own, which it
    refuses. GitHub answers an empty repository's list with none or with
    409, "Git Repository is empty"; both say so."""
    try:
        return not github.listed(f"{repo_path(repository)}/branches?per_page=1")
    except GitHubError as refusal:
        if refusal.status == EMPTY_STATUS:
            return True
        raise


def has_adopt_branch(github, repository):
    """matching-refs matches by prefix, so the ref is checked to be exactly
    symphony/adopt, or its old name, and not a branch that merely starts so."""
    for branch, ref in ((ADOPT_BRANCH, ADOPT_REF), (OLD_ADOPT_BRANCH, OLD_ADOPT_REF)):
        refs = github.listed(f"{repo_path(repository)}/git/matching-refs/heads/{branch}")
        if any(isinstance(found, dict) and found.get("ref") == ref for found in refs):
            return True
    return False


def is_adopted(github, repository):
    """Whether docs/agents/PROTOCOL.md is on the default branch, which every
    adoption brings, since scripts/adopt.py apply refuses one that could not
    write it: the one rule for an adoption already made, which the
    installation's path asks through unadopted and a repository named on
    the form through scripts/adopted.py."""
    return found(github, f"{repo_path(repository)}/contents/{PROTOCOL_TEXT}")


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
    """The switch under its name or its old one; either saying off is out."""
    for path in (OPT_OUT, OLD_OPT_OUT):
        try:
            answer = github.call("GET", f"{repo_path(repository)}/contents/{path}")
        except GitHubError as refusal:
            if refusal.status == 404:
                continue
            raise
        if switch_word(answer) == "off":
            return True
    return False


# --- the kind ---------------------------------------------------------------------


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
