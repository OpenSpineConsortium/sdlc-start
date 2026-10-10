#!/usr/bin/env python3
"""Adopt the OpenSpine SDLC template into a repository, from the form.

.github/workflows/adopt.yml runs one subcommand per step:

  parse  reads the issue the adoption form made and prints its fields as
         KEY=value lines for $GITHUB_OUTPUT. Anyone can open an issue, so
         anything the form would not have written is refused, with one
         line of reason that never quotes the issue back.
  apply  copies the template into the checkout of the person's repository
         and writes a manifest of what it added, replaced, kept, merged
         and skipped. Mode new is the whole template, as "Use this
         template" makes it: the tree is staged, the template's own
         tools/template_init.py fills it there, so the fill has one
         source, and a file the repository has already is replaced. Mode
         existing is the protocol only, the files the template's guide
         for a repository it did not make has a person copy by hand, so
         the template's tests, checks and documents never meet the
         person's; nothing there is overwritten, a workflow and the
         script it runs come together or not at all, a file the
         repository ignores is never written, the protocol's text is the
         library's spec when --protocol-spec names it, CLAUDE.md gains
         one section once that text has landed, and .claude/settings.json
         the keys that enable the sdlc plugin.
  body   prints the pull request's text from the manifest, or with
         --title its title.
  labels prints the board's labels, read from the template's own list.

LICENSE is never copied: licensing the person's project is their
decision. A link in the template is never followed and a path of the
target that a link would carry out of the repository, or into its .git,
is never written. Python 3.12 or later, standard library only.
"""

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

MANIFEST_SCHEMA = "sdlc-adopt/1"

# The form as .github/ISSUE_TEMPLATE/adopt.yml words it: each field's
# label is a "### " heading of the issue's body, followed by its value.
# tests/test_form.py holds the two files to the same words.
FIELD_REPOSITORY = "Repository"
FIELD_KIND = "Kind"
FIELD_METRICS = "Metrics"
FIELD_APP = "The App"
FIELDS = (FIELD_REPOSITORY, FIELD_KIND, FIELD_METRICS, FIELD_APP)
KINDS = {
    "New repository: the whole template": "new",
    "Existing repository: the protocol only": "existing",
}
SHARING = {
    "Share anonymous aggregates (default)": "on",
    "Do not share": "off",
}
APP_INSTALLED = "The OpenSpine SDLC App is installed on this repository"
HEADING = re.compile(r"### (.+)")
TICKED = re.compile(r"- \[[xX]\] (.+)")

REPOSITORY = re.compile(r"[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}")
LOGIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}")
OWNER_TYPES = ("User", "Organization")
# The front door and the template take no adoption of themselves.
OWN_REPOSITORIES = ("openspineconsortium/sdlc-template", "openspineconsortium/sdlc-start")

# Never copied from the template: git's own folder, Python's caches.
SKIPPED_NAMES = {".git", "__pycache__"}
INIT_SCRIPT = "tools/template_init.py"

# Mode existing: the protocol and nothing else.
PROTOCOL_TREE = "tools/sdlc_protocol"
PROTOCOL_FILES = (
    "tools/VENDORED",
    "tools/board.py",
    ".github/workflows/board.yml",
    ".github/workflows/tidy.yml",
    "docs/agents/claims/README.md",
)
PROTOCOL_TEXT = "docs/agents/PROTOCOL.md"
VENDORED = "tools/VENDORED"
BOARD_WORKFLOW = ".github/workflows/board.yml"
METRICS_WORKFLOW = ".github/workflows/metrics.yml"
# The template's field metrics, copied in both modes once it carries both.
METRICS_FILES = (METRICS_WORKFLOW, "tools/metrics.py")
SWITCH = ".github/sdlc-metrics"
# Mode existing brings a workflow and the script it runs together or not
# at all: the template's workflow would run a script of theirs by the same
# name, with contents: write, and theirs would run the template's. The
# vendored library and its record are one unit the same way, so a release's
# modules never lie next to an older copy's.
UNITS = (
    ("the board's workflow and its script", (BOARD_WORKFLOW, "tools/board.py")),
    ("the metrics workflow and its script", METRICS_FILES),
)
LIBRARY_UNIT = "the vendored library and its record"
# A file the repository ignores is committed only by force, and git then
# replaces each person's own copy of it on their next pull without a word.
IGNORED_WHY = "ignored by this repository, so each person's own copy would be replaced on pull"
CLAUDE_MD = "CLAUDE.md"
SETTINGS = ".claude/settings.json"
# Team mode's labels need the template's other workflows, which mode
# existing does not bring.
TEAM_LABELS = ("epic", "blocked")

# The section a repository's CLAUDE.md gains, in the words of the
# template's guide: the @ line imports the protocol into every session.
CLAUDE_SECTION = (
    "## How work is claimed\n"
    "\n"
    "@docs/agents/PROTOCOL.md\n"
    "\n"
    "Before any work: fetch, read the board with `git fetch origin board && git show origin/board:STATE.md`,"
    " and check the claim on the issue you mean to take. One issue, one branch `claude/<issue>`, one pull"
    " request. Never push to the default branch or to another account's claim branch.\n"
)
CLAUDE_IMPORT = "@docs/agents/PROTOCOL.md"
# The project preset of OpenSpineConsortium/sdlc-marketplace's README.
MARKETPLACE_NAME = "sdlc-marketplace"
MARKETPLACE = {
    "source": {"source": "github", "repo": "OpenSpineConsortium/sdlc-marketplace"},
    "autoUpdate": True,
}
PLUGIN = "sdlc@sdlc-marketplace"

FRONT_DOOR = "https://github.com/OpenSpineConsortium/sdlc-start"


class FormError(Exception):
    """The issue is not one the form writes; one line that quotes nothing of it."""


class AdoptError(Exception):
    """Something apply or labels cannot do; one line."""


# --- parse ------------------------------------------------------------------------


def form_sections(body):
    """Each "### " heading of the body with the text under it, stripped."""
    sections, current = {}, None
    for line in body.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        heading = HEADING.fullmatch(line.rstrip())
        if heading:
            current = heading.group(1).strip()
            if current in sections:
                raise FormError("a field appears twice, so the issue is not the adoption form's")
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def parse_repository(value):
    """OWNER/NAME as GitHub allows it, or FormError."""
    shape = "the repository must be written as OWNER/NAME, such as octo-org/my-project, with no link and no spaces"
    if not REPOSITORY.fullmatch(value):
        raise FormError(shape)
    owner, name = value.split("/")
    if owner.startswith("-") or name in (".", "..") or name.lower().endswith(".git"):
        raise FormError(shape)
    if value.lower() in OWN_REPOSITORIES:
        raise FormError("that repository is part of the OpenSpine SDLC itself and takes no adoption")
    return owner, name


def choose(value, options, field):
    """The option's short name, or FormError."""
    if value not in options:
        raise FormError(f"the field {field} holds none of the form's options")
    return options[value]


def is_ticked(value):
    found = TICKED.fullmatch(value)
    return bool(found) and found.group(1).strip() == APP_INSTALLED


def parse_form(body):
    """The form's fields: repository, owner, name, mode and metrics."""
    sections = form_sections(body)
    if set(sections) != set(FIELDS):
        raise FormError("the issue is not the adoption form's")
    owner, name = parse_repository(sections[FIELD_REPOSITORY])
    mode = choose(sections[FIELD_KIND], KINDS, FIELD_KIND)
    metrics = choose(sections[FIELD_METRICS], SHARING, FIELD_METRICS)
    if not is_ticked(sections[FIELD_APP]):
        raise FormError("the box that says the App is installed on the repository is not ticked")
    return {"repository": f"{owner}/{name}", "owner": owner, "name": name, "mode": mode, "metrics": metrics}


def command_parse(options):
    try:
        if options.body in (None, "-"):
            body = sys.stdin.read()
        else:
            body = Path(options.body).read_text(encoding="utf-8")
        fields = parse_form(body)
    except (OSError, UnicodeDecodeError):
        print("the issue's body could not be read", file=sys.stderr)
        return 1
    except FormError as problem:
        print(problem, file=sys.stderr)
        return 1
    for key, value in fields.items():
        print(f"{key}={value}")
    return 0


# --- the template's tree ----------------------------------------------------------


def relative(path, root):
    return path.relative_to(root).as_posix()


def template_files(template):
    """The template's regular files and the links met on the way, both as
    relative paths. A link is never followed, whether it leads out of the
    template or not: the copy holds files only."""
    files, links = [], []
    for folder, dirs, names in os.walk(template):
        here = Path(folder)
        for name in list(dirs):
            if name in SKIPPED_NAMES or (here / name).is_symlink():
                dirs.remove(name)
                if name not in SKIPPED_NAMES:
                    links.append(relative(here / name, template))
        for name in names:
            path = here / name
            if name in SKIPPED_NAMES:
                continue
            if path.is_symlink():
                links.append(relative(path, template))
            elif path.is_file():
                files.append(relative(path, template))
    return sorted(files), sorted(links)


def is_license(rel):
    """A top-level LICENSE, LICENSE.md and the like."""
    parts = PurePosixPath(rel).parts
    return len(parts) == 1 and parts[0].upper().startswith("LICENSE")


def stage(template, staging, files):
    """Copy the files into staging, permission bits included, so a script
    stays executable."""
    for rel in files:
        if is_license(rel):
            continue
        destination = staging / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(template / rel, destination)


def write_event(path, repo, owner_type, creator):
    """The event a "Use this template" push would carry, as far as
    template_init reads it: whose repository it is and who made the copy,
    so .github/CODEOWNERS names the person in an organization's copy."""
    event = {
        "repository": {"full_name": repo, "owner": {"type": owner_type}},
        "sender": {"type": "User", "login": creator},
    }
    path.write_text(json.dumps(event) + "\n", encoding="utf-8")


def init_script(template):
    script = template / INIT_SCRIPT
    if script.is_symlink() or not script.is_file():
        raise AdoptError(f"the template has no {INIT_SCRIPT}")
    return script


def run_template_init(template, staging, event, repo, default_branch):
    """Fill the staged tree with the template's own init, which also removes
    its marker folder and blanks the checkpoint. It runs without a token, so
    it makes no label and opens no issue; its output stays out of the log."""
    command = [
        sys.executable, "-B", str(init_script(template)),
        "--repo", repo, "--default-branch", default_branch,
        "--root", str(staging), "--event", str(event),
    ]
    env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_EVENT_PATH")}
    done = subprocess.run(command, cwd=staging.parent, env=env, capture_output=True, text=True)
    if done.returncode != 0:
        last = (done.stderr.strip().splitlines() or ["no message"])[-1]
        raise AdoptError(f"the template's {INIT_SCRIPT} failed: {last}")


def read_plan(staging):
    """Every staged file as relative path -> (bytes, executable)."""
    files, _ = template_files(staging)
    return {rel: ((staging / rel).read_bytes(), bool((staging / rel).stat().st_mode & 0o111)) for rel in files}


def read_spec(options):
    """The library's spec/PROTOCOL.md as a plan entry when --protocol-spec
    names it, else None. The vendored copy never carries the spec, so the
    workflow clones the public library at the commit tools/VENDORED names
    and passes the file; without it mode existing falls back to the
    template's own page, which names files only a copy of the template
    has, and the body says so."""
    if options.protocol_spec is None:
        return None
    path = Path(options.protocol_spec)
    if path.is_symlink() or not path.is_file():
        raise AdoptError("--protocol-spec is not a file")
    return path.read_bytes(), False


def protocol_plan(staged, spec):
    """Mode existing's files out of the staged tree, and where the protocol's
    text came from: the library's spec when one was passed, the template's
    own filled page otherwise."""
    plan = {rel: entry for rel, entry in staged.items() if rel.startswith(PROTOCOL_TREE + "/")}
    for rel in PROTOCOL_FILES:
        if rel not in staged:
            raise AdoptError(f"the template has no {rel}")
        plan[rel] = staged[rel]
    if spec is None and PROTOCOL_TEXT not in staged:
        raise AdoptError(f"the template has no {PROTOCOL_TEXT}")
    plan[PROTOCOL_TEXT] = staged[PROTOCOL_TEXT] if spec is None else spec
    if all(rel in staged for rel in METRICS_FILES):
        plan.update({rel: staged[rel] for rel in METRICS_FILES})
    plan[SWITCH] = staged[SWITCH]
    return plan, ("template" if spec is None else "spec")


def staged_plan(template, options):
    """What goes into the target, staged and filled in a scratch folder that
    lies in neither tree."""
    spec = read_spec(options)
    files, links = template_files(template)
    with tempfile.TemporaryDirectory(prefix="sdlc-adopt-") as scratch:
        staging = Path(scratch) / "tree"
        staging.mkdir()
        stage(template, staging, files)
        event = Path(scratch) / "event.json"
        write_event(event, options.repo, options.owner_type, options.creator)
        run_template_init(template, staging, event, options.repo, options.default_branch)
        (staging / SWITCH).parent.mkdir(parents=True, exist_ok=True)
        (staging / SWITCH).write_text(options.metrics + "\n", encoding="ascii")
        staged = read_plan(staging)
    if options.mode == "new":
        return staged, links, "template"
    plan, text = protocol_plan(staged, spec)
    return plan, links, text


# --- the target -------------------------------------------------------------------


def inside(path, root):
    return os.path.commonpath([path, root]) == root


def safe_relative(rel):
    path = PurePosixPath(rel)
    if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] == ".git":
        raise AdoptError(f"{rel}: not a path inside the repository; refused")
    return path


def blocked(target, rel):
    """Why the file rel of the target is not written, or None. A link may
    lead anywhere inside the repository but never out of it nor into its
    .git, where a hook would run at the commit."""
    path = safe_relative(rel)
    parent = os.path.realpath(target / path.parent)
    if not inside(parent, str(target)):
        return "a folder on its way is a link that leads out of the repository"
    if inside(parent, str(target / ".git")):
        return "a folder on its way is a link into .git"
    for depth in range(1, len(path.parts)):
        ancestor = target.joinpath(*path.parts[:depth])
        if (ancestor.is_symlink() or ancestor.exists()) and not ancestor.is_dir():
            return "a file of yours stands where a folder goes"
    destination = target / path
    if destination.is_dir() and not destination.is_symlink():
        return "a folder of yours stands where this file goes"
    return None


def write_file(destination, data, executable):
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    os.chmod(destination, 0o755 if executable else 0o644)


def place(target, rel, data, executable, overwrite):
    """Write one file; the outcome and, when skipped, why."""
    why = blocked(target, rel)
    if why:
        return "skipped", why
    destination = target / rel
    if exists(destination):
        if not overwrite:
            return "kept", None
        destination.unlink()  # a link is replaced, never written through
        write_file(destination, data, executable)
        return "replaced", None
    write_file(destination, data, executable)
    return "added", None


def record(manifest, rel, outcome, why=None):
    if outcome == "skipped":
        manifest["skipped"].append({"path": rel, "why": why})
    else:
        manifest[outcome].append(rel)


def existing_file(target, rel):
    """The file of theirs that rel names, as (path, None) when it may be
    read and rewritten in place, a regular file or a link that stays inside
    the repository, or (None, why) when it may not."""
    why = blocked(target, rel)
    if why:
        return None, why
    real = os.path.realpath(target / rel)
    if not inside(real, str(target)) or inside(real, str(target / ".git")):
        return None, "it is a link that leads out of the repository or into .git"
    if not Path(real).is_file():
        return None, "it is a link to something that is not a file"
    return Path(real), None


def exists(path):
    return path.is_symlink() or path.exists()


def is_checkout(target):
    """Whether target is the top of a git checkout, where ignore rules
    apply; a plain folder has none."""
    if not exists(target / ".git"):
        return False
    done = subprocess.run(["git", "-C", str(target), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return done.returncode == 0 and os.path.realpath(done.stdout.strip()) == os.path.realpath(target)


def ignored_paths(target, rels):
    """Those of rels that the target's ignore rules match; a file git tracks
    is never among them, whatever the rules say."""
    if not is_checkout(target):
        return set()
    done = subprocess.run(["git", "-C", str(target), "check-ignore", "-z", "--stdin"],
                          input="\0".join(rels), capture_output=True, text=True)
    if done.returncode not in (0, 1):  # 0 names some of them, 1 names none
        last = (done.stderr.strip().splitlines() or ["no message"])[-1]
        raise AdoptError(f"the repository's ignore rules could not be read: {last}")
    return {rel for rel in done.stdout.split("\0") if rel}


def in_the_way(target, rel, ignored):
    """Why rel would not be added, as a clause about it, or None."""
    if blocked(target, rel):
        return "cannot be written here"
    if exists(target / rel):
        return "is this repository's own"
    if rel in ignored:
        return "is ignored by this repository"
    return None


def unit_holdbacks(target, plan, ignored):
    """rel -> why, for each file of a unit that would be added while another
    file of the unit is theirs, blocked or ignored: the unit is then left
    whole, and the file that stands in the way is named."""
    units = [(name, [rel for rel in files if rel in plan]) for name, files in UNITS]
    units.append((LIBRARY_UNIT, [rel for rel in plan if rel.startswith(PROTOCOL_TREE + "/") or rel == VENDORED]))
    held = {}
    for name, files in units:
        causes = {rel: in_the_way(target, rel, ignored) for rel in files}
        standing = [rel for rel in files if causes[rel]]
        if standing:
            other = standing[0]
            for rel in files:
                if not causes[rel]:
                    held[rel] = f"`{other}` {causes[other]}, and {name} are brought together or not at all"
    return held


def with_section(text):
    """Their CLAUDE.md with the section after it, in their line endings."""
    section = CLAUDE_SECTION
    if b"\r\n" in text:
        section = section.replace("\n", "\r\n")
    newline = b"\r\n" if b"\r\n" in text else b"\n"
    if text and not text.endswith(newline):
        text += newline
    return text + newline + section.encode("utf-8")


def note_missing_protocol(manifest):
    """Say why CLAUDE.md gains no section: the protocol's text did not land,
    so there is nothing of the template's to import."""
    if PROTOCOL_TEXT in manifest["kept"]:
        cause = "is this repository's own and is kept"
    else:
        cause = "was not written (above)"
    manifest["notes"].append(
        f"`{PROTOCOL_TEXT}` {cause}, so the claim protocol's text did not land and `{CLAUDE_MD}` gains no section"
        " importing it. The text is spec/PROTOCOL.md in the public OpenSpineConsortium/sdlc-protocol; once it"
        f" stands at `{PROTOCOL_TEXT}`, add this to `{CLAUDE_MD}`:\n\n```markdown\n{CLAUDE_SECTION}```"
    )


def add_claude_section(target, manifest, ignored):
    """Append the section to their CLAUDE.md, or make one with it, once the
    protocol's text it imports has landed; an ignored CLAUDE.md is each
    person's own and is left alone."""
    if PROTOCOL_TEXT not in manifest["added"]:
        note_missing_protocol(manifest)
        return
    if CLAUDE_MD in ignored:
        record(manifest, CLAUDE_MD, "skipped", IGNORED_WHY)
        return
    if not exists(target / CLAUDE_MD):
        record(manifest, CLAUDE_MD, *place(target, CLAUDE_MD, CLAUDE_SECTION.encode("utf-8"), False, False))
        return
    real, why = existing_file(target, CLAUDE_MD)
    if why:
        record(manifest, CLAUDE_MD, "skipped", why)
        return
    text = real.read_bytes()
    if CLAUDE_IMPORT in text.decode("utf-8", "replace"):
        record(manifest, CLAUDE_MD, "kept")
        return
    real.write_bytes(with_section(text))
    manifest["merged"].append(CLAUDE_MD)


def json_indent(text):
    """The indent their JSON uses, so a merge keeps its look."""
    for line in text.splitlines()[1:]:
        stripped = line.lstrip(" \t")
        if stripped and len(stripped) < len(line):
            lead = line[: len(line) - len(stripped)]
            return "\t" if lead.startswith("\t") else len(lead)
    return 2


def keys_appended(text, additions, indent):
    """Their text with new top-level keys written before its closing brace,
    so every line they had stays as it was; None when the text does not end
    with that brace."""
    body = text.rstrip()
    if not body.endswith("}"):
        return None
    head = body[:-1].rstrip()
    newline = "\r\n" if "\r\n" in text else "\n"
    unit = "\t" if indent == "\t" else " " * indent
    members = []
    for key, value in additions.items():
        dumped = json.dumps(value, indent=indent, ensure_ascii=False).replace("\n", newline + unit)
        members.append(f"{unit}{json.dumps(key)}: {dumped}")
    separator = "" if head.endswith("{") else ","
    return head + separator + newline + ("," + newline).join(members) + newline + "}" + newline


def merged_settings(text):
    """Their settings with the marketplace and the plugin added: the text,
    what each key gained ("added" when the key is new, "extended" when it
    took one entry) and whether the plugin ends up enabled; None when
    nothing changes. ValueError when it is not a JSON object of the shape
    Claude Code reads. When the keys are new, they are written after their
    text, which stays as it was; otherwise, or when that would not read
    back as the merge, the whole file is written again, in its own line
    endings."""
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("not an object")
    markets = data.get("extraKnownMarketplaces", {})
    plugins = data.get("enabledPlugins", {})
    if not isinstance(markets, dict) or not isinstance(plugins, dict):
        raise ValueError("extraKnownMarketplaces or enabledPlugins is not an object")
    if MARKETPLACE_NAME in markets and PLUGIN in plugins:
        return None
    merged, changed = dict(data), {}
    if MARKETPLACE_NAME not in markets:
        merged["extraKnownMarketplaces"] = {**markets, MARKETPLACE_NAME: MARKETPLACE}
        changed["extraKnownMarketplaces"] = "extended" if "extraKnownMarketplaces" in data else "added"
    if PLUGIN not in plugins:
        merged["enabledPlugins"] = {**plugins, PLUGIN: True}
        changed["enabledPlugins"] = "extended" if "enabledPlugins" in data else "added"
    enabled = merged["enabledPlugins"].get(PLUGIN) is True
    indent = json_indent(text)
    newline = "\r\n" if "\r\n" in text else "\n"
    if all(state == "added" for state in changed.values()):
        appended = keys_appended(text, {key: merged[key] for key in changed}, indent)
        if appended is not None and json.loads(appended) == merged:
            return appended, changed, enabled
    return (json.dumps(merged, indent=indent, ensure_ascii=False) + "\n").replace("\n", newline), changed, enabled


def preset_settings():
    return json.dumps({"extraKnownMarketplaces": {MARKETPLACE_NAME: MARKETPLACE}, "enabledPlugins": {PLUGIN: True}},
                      indent=2) + "\n"


def merge_settings(target, manifest, ignored):
    """Add the keys to their .claude/settings.json, keeping every key it has;
    make the file when there is none; leave it when it does not parse or
    when the repository ignores it."""
    if SETTINGS in ignored:
        record(manifest, SETTINGS, "skipped", IGNORED_WHY)
        return
    if not exists(target / SETTINGS):
        outcome, why = place(target, SETTINGS, preset_settings().encode("ascii"), False, False)
        record(manifest, SETTINGS, outcome, why)
        if outcome == "added":
            manifest["settings_changed"] = {"extraKnownMarketplaces": "added", "enabledPlugins": "added"}
            manifest["plugin_enabled"] = True
        return
    real, why = existing_file(target, SETTINGS)
    if why:
        record(manifest, SETTINGS, "skipped", why)
        return
    try:
        text = real.read_bytes().decode("utf-8-sig")
        merged = merged_settings(text)
    except ValueError:  # UnicodeDecodeError and JSONDecodeError are both ValueErrors
        record(manifest, SETTINGS, "kept")
        manifest["settings_invalid"] = True
        return
    if merged is None:
        record(manifest, SETTINGS, "kept")
        return
    written, changed, enabled = merged
    real.write_bytes(written.encode("utf-8"))
    manifest["merged"].append(SETTINGS)
    manifest["settings_changed"] = changed
    manifest["plugin_enabled"] = enabled


def first_word(text):
    """The switch as the template's tools/metrics.py reads it: the first
    whitespace-separated word, lowercased; the rest of the file is prose."""
    words = (text or "").split()
    return words[0].lower() if words else ""


def note_kept_switch(target, manifest, metrics):
    """Say so when mode existing kept a switch that says something else than
    the form asked."""
    if SWITCH not in manifest["kept"]:
        return
    real, _ = existing_file(target, SWITCH)
    said = first_word(real.read_text(encoding="utf-8", errors="replace")) if real else ""
    if said != metrics:
        if said in ("on", "off"):
            shown = f"`{said}`"
        else:
            shown = "something other than on or off, which the metrics workflow reads as off"
        manifest["notes"].append(
            f"{SWITCH} was there already and says {shown}, where the form asked for `{metrics}`;"
            " it is kept, so edit it to change the choice."
        )


# --- apply ------------------------------------------------------------------------


def checked_options(options):
    """Refuse what the workflow could only pass by mistake."""
    try:
        parse_repository(options.repo)
    except FormError as problem:
        raise AdoptError(f"--repo: {problem}") from None
    if not LOGIN.fullmatch(options.creator):
        raise AdoptError("--creator must be a GitHub login")
    branch = options.default_branch
    if not branch or branch.startswith("-") or any(c.isspace() or ord(c) < 32 or c == "\x7f" for c in branch):
        raise AdoptError("--default-branch must be a branch name")


def checked_roots(options):
    template = Path(options.template).resolve()
    target = Path(options.target).resolve()
    manifest = Path(options.manifest).resolve()
    for name, root in (("--template", template), ("--target", target)):
        if not root.is_dir():
            raise AdoptError(f"{name} is not a folder")
    if inside(str(template), str(target)) or inside(str(target), str(template)):
        raise AdoptError("--template and --target must be two folders, neither inside the other")
    if inside(str(manifest), str(target)):
        raise AdoptError("--manifest must lie outside the target, or it would be committed")
    return template, target, manifest


def new_manifest(options, links, protocol_text, plan):
    return {
        "schema": MANIFEST_SCHEMA,
        "repository": options.repo,
        "mode": options.mode,
        "metrics": options.metrics,
        "default_branch": options.default_branch,
        "owner_type": options.owner_type,
        "creator": options.creator,
        "metrics_workflow": False,  # known once the files have landed
        "metrics_in_template": all(rel in plan for rel in METRICS_FILES),
        "protocol_text": protocol_text,
        "added": [], "replaced": [], "kept": [], "merged": [],
        "skipped": [{"path": rel, "why": "a link in the template, which is never followed"} for rel in links],
        "notes": [],
        "settings_invalid": False,
        "settings_changed": {},
        "plugin_enabled": None,
    }


def adopt(options):
    """Apply the adoption to the target and write the manifest; the manifest."""
    checked_options(options)
    template, target, manifest_path = checked_roots(options)
    plan, links, protocol_text = staged_plan(template, options)
    manifest = new_manifest(options, links, protocol_text, plan)
    ignored, held = set(), {}
    if options.mode == "existing":
        ignored = ignored_paths(target, sorted(plan) + [CLAUDE_MD, SETTINGS])
        held = unit_holdbacks(target, plan, ignored)
    for rel in sorted(plan):
        if rel in ignored:
            record(manifest, rel, "skipped", IGNORED_WHY)
        elif rel in held:
            record(manifest, rel, "skipped", held[rel])
        else:
            data, executable = plan[rel]
            record(manifest, rel, *place(target, rel, data, executable, options.mode == "new"))
    if options.mode == "existing":
        add_claude_section(target, manifest, ignored)
        merge_settings(target, manifest, ignored)
        note_kept_switch(target, manifest, options.metrics)
    landed = manifest["added"] + manifest["replaced"]
    manifest["metrics_workflow"] = all(rel in landed for rel in METRICS_FILES)
    for key in ("added", "replaced", "kept", "merged"):
        manifest[key].sort()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def command_apply(options):
    try:
        manifest = adopt(options)
    except (AdoptError, OSError) as problem:
        print(f"adopt: {problem}", file=sys.stderr)
        return 1
    counts = ", ".join(f"{len(manifest[key])} {key}" for key in ("added", "replaced", "kept", "merged", "skipped"))
    print(f"adopt: mode {manifest['mode']}: {counts}")
    return 0


# --- body -------------------------------------------------------------------------


def path_list(paths):
    return "\n".join(f"- `{path}`" for path in paths)


def folded(summary, paths):
    """A long list folded away, so the page opens on what matters."""
    return f"<details><summary>{summary}</summary>\n\n{path_list(paths)}\n\n</details>"


def title(manifest):
    if manifest["mode"] == "new":
        return "Adopt the OpenSpine SDLC template"
    return "Take up the OpenSpine SDLC claim protocol"


def opening(manifest):
    repo = manifest["repository"]
    asked = (f"The OpenSpine SDLC App opened it because an administrator of {repo} asked for it on the adoption"
             f" form ({FRONT_DOOR}). Nothing changes until you merge it.")
    if manifest["mode"] == "new":
        return (f"This pull request brings the whole OpenSpine SDLC template into {repo}, as \"Use this template\""
                f" would have made it, with this repository's names filled in. {asked}")
    return (f"This pull request brings the OpenSpine SDLC claim protocol into {repo}, beside your own files: the"
            " board, the claim files and the text every Claude Code session reads before it takes work. No file of"
            f" yours is overwritten. {asked}")


def key_phrase(key, changed):
    return f"`{key}`" if changed[key] == "added" else f"an entry in `{key}`"


def settings_line(manifest):
    """What .claude/settings.json gained, naming only the keys it did and
    the plugin's state when it stays off by their choice."""
    changed = manifest["settings_changed"]
    gained = []
    if "extraKnownMarketplaces" in changed:
        gained.append(f"{key_phrase('extraKnownMarketplaces', changed)}, which names the marketplace"
                      " OpenSpineConsortium/sdlc-marketplace")
    if "enabledPlugins" in changed:
        gained.append(f"{key_phrase('enabledPlugins', changed)}, which enables its plugin `{PLUGIN}`")
    line = f"- `{SETTINGS}` gains " + ", and ".join(gained)
    if not manifest["plugin_enabled"]:
        line += f"; its plugin `{PLUGIN}` stays off in `enabledPlugins`, as you set it"
    return line + "; every key it had stays."


def merged_lines(manifest):
    lines = []
    if CLAUDE_MD in manifest["merged"]:
        lines.append(f"- `{CLAUDE_MD}` gains the section \"How work is claimed\" at its end, whose `{CLAUDE_IMPORT}`"
                     " line imports the protocol into every session.")
    if SETTINGS in manifest["merged"]:
        lines.append(settings_line(manifest))
    return lines


def by_reason(skipped):
    """The paths not written, grouped under each reason in the order the
    reasons first appear, as `a`, `b` and `c`."""
    groups = {}
    for item in skipped:
        groups.setdefault(item["why"], []).append(f"`{item['path']}`")
    listed = []
    for why, paths in groups.items():
        listed.append((", ".join(paths[:-1]) + " and " + paths[-1] if len(paths) > 1 else paths[0], why))
    return listed


def changes_section(manifest):
    parts = ["## What changes", ""]
    added = manifest["added"]
    if added:
        parts += [f"Added, {len(added)} files:", "", folded(f"The {len(added)} added files", added), ""]
    if manifest["replaced"]:
        parts += ["Replaced, files this repository had that the template's copy takes the place of; the diff shows"
                  " what they held:", "", path_list(manifest["replaced"]), ""]
    if manifest["mode"] == "new":
        parts += ["Files of yours that the template does not have are not touched.", ""]
    merged = merged_lines(manifest)
    if merged:
        parts += ["Changed by addition only:", "", *merged, ""]
    if manifest["kept"]:
        parts += ["Kept as they are, because this repository has them already:", "", path_list(manifest["kept"]), ""]
    if manifest["skipped"]:
        parts += ["Not written:", ""]
        parts += [f"- {paths}: {why}" for paths, why in by_reason(manifest["skipped"])]
        parts.append("")
    parts += ["LICENSE is not touched: licensing your project is your decision, so the template's is not copied.", ""]
    return parts


def ignored_notes(ignored):
    """What to do about the files the repository ignores, which were not
    written, each with what this pull request would have put there."""
    parts = ["Files this repository ignores were not written, since git replaces each person's own copy of an"
             " ignored file on their next pull without a word. Stop ignoring them and ask again on the form, or do"
             " by hand what this pull request would have done:", ""]
    if CLAUDE_MD in ignored:
        parts += [f"- `{CLAUDE_MD}`: add this section to the `{CLAUDE_MD}` each session reads.", "",
                  "```markdown", CLAUDE_SECTION.rstrip("\n"), "```", ""]
    if SETTINGS in ignored:
        parts += [f"- `{SETTINGS}`: each person adds the marketplace and installs the plugin once, with"
                  " `claude plugin marketplace add OpenSpineConsortium/sdlc-marketplace` and"
                  f" `claude plugin install {PLUGIN}`, or adds these keys to the settings file they keep.", "",
                  "```json", preset_settings().rstrip("\n"), "```", ""]
    others = [rel for rel in ignored if rel not in (CLAUDE_MD, SETTINGS)]
    if others:
        parts += ["- " + ", ".join(f"`{rel}`" for rel in others) + ": their content is not in this pull request;"
                  " ask again once they are no longer ignored.", ""]
    return parts


def notes_section(manifest):
    parts = []
    if manifest["settings_invalid"]:
        parts += [f"`{SETTINGS}` does not parse as a JSON object, so it was left as it was. Add these two keys to it"
                  " by hand once it does, beside the keys it has:", "", "```json", preset_settings().rstrip("\n"),
                  "```", ""]
    templates_page = manifest["protocol_text"] == "template" and PROTOCOL_TEXT in manifest["added"]
    if manifest["mode"] == "existing" and templates_page:
        parts += [f"`{PROTOCOL_TEXT}` is the template's own text, which also names files only a copy of the"
                  " template carries (its skills, routines and setup pages); the sdlc plugin brings the skills.", ""]
    ignored = [item["path"] for item in manifest["skipped"] if item["why"] == IGNORED_WHY]
    if ignored:
        parts += ignored_notes(ignored)
    if manifest["mode"] == "new" and manifest["owner_type"] == "Organization":
        parts += [f"`.github/CODEOWNERS` names `{manifest['creator']}`, who asked for this pull request, because GitHub"
                  " asks a user or a team for review and never an organization; change it by pull request when"
                  " someone else should review (docs/setup/github.md, section 7).", ""]
    parts += [f"{note}\n" for note in manifest["notes"]]
    return (["## Notes", "", *parts]) if parts else []


def sharing_section(manifest):
    parts = ["## What is shared", ""]
    if manifest["metrics"] == "on":
        parts.append(f"Sharing of anonymous aggregates is on: `{SWITCH}` says `on`.")
        if manifest["metrics_workflow"]:
            parts.append("Once a day `.github/workflows/metrics.yml` writes METRICS.json to the branch `metrics`:"
                         " counts, durations and rates of the protocol at work, and never code, text, titles,"
                         " logins, branch names or repository names. The OpenSpine SDLC App reads that branch's"
                         " METRICS.json, and JUDGE.json, the failure-type frequencies that someone's own judge"
                         " writes when they run it on their own machine and Claude account, and nothing else; the"
                         " dataset names this repository only by a salted hash.")
        elif manifest["metrics_in_template"]:
            parts.append("The metrics workflow was not written (above), so nothing is computed or shared today; the"
                         " switch records your choice for when it is.")
        else:
            parts.append("The template does not carry its metrics workflow yet, so nothing is computed or shared"
                         " today; the switch records your choice for when it does.")
        parts.append(f"To turn it off at any time, write `off` in `{SWITCH}` on the default branch, or set the"
                     " repository variable SDLC_METRICS to `off`; uninstalling the App stops it too.")
    else:
        parts.append(f"Nothing is shared: `{SWITCH}` says `off`, so the metrics workflow, where there is one, writes"
                     " only that sharing is off. Write `on` there to share anonymous aggregates later.")
    return parts[:2] + [" ".join(parts[2:]), ""]


def next_steps_new(manifest):
    repo = manifest["repository"]
    return [
        "1. Read this pull request, then merge it.",
        "2. From a clone, on your own computer, with the GitHub CLI signed in as an administrator, run"
        " `bash scripts/setup-repo.sh`: the default branch's rules, delete-on-merge and auto-merge, secret scanning,"
        " the labels and a check of `.github/CODEOWNERS`. `docs/setup/owner-checklist.md` has the rest: the Claude"
        " GitHub App and its token, the Projects and the routines.",
        "   For a project worked by volunteers on their own Claude accounts, run instead"
        f" `python3 scripts/crowd.py setup {repo} --area AREA` and, after reading the pull request it opens,"
        f" `python3 scripts/crowd.py finish {repo}`, as `docs/setup/crowdsourcing.md`, Part 1, says;"
        " setup-repo.sh refuses to run once crowd mode is on.",
        "3. Write the goal in `docs/project.md` and the owners in `docs/agents/OWNERSHIP.md`.",
        "4. Run `bash scripts/check.sh` once; CI runs the same as the check named \"check\".",
    ]


def next_steps_existing(manifest):
    """The steps after the merge, said for the files that landed: a workflow
    held back has no branch to protect against and renders no board."""
    repo = manifest["repository"]
    added = manifest["added"]
    forced = [name for rel, name in ((BOARD_WORKFLOW, "`board`"), (METRICS_WORKFLOW, "`metrics`")) if rel in added]
    protect = (f"3. Protect the default branch, and only it, at https://github.com/{repo}/settings/rules: require a"
               " pull request and your own checks, and block force pushes and deletions.")
    if forced:
        protect += f" Never target {' or '.join(forced)}, which the workflows force-push."
    if BOARD_WORKFLOW in added:
        board = ("4. After the merge the next issue event renders the board at"
                 f" https://github.com/{repo}/blob/board/STATE.md; `gh workflow run board.yml --repo {repo}` renders"
                 " it now.")
    else:
        board = (f"4. `{BOARD_WORKFLOW}` was not written (above), so nothing renders the board until the board's"
                 " workflow and its script are brought together by hand.")
    protocol = PROTOCOL_TEXT if PROTOCOL_TEXT in added else "the sdlc plugin's claim protocol"
    return [
        "1. Read this pull request, then merge it.",
        "2. Each person who works here runs this once, after trusting the folder in Claude Code, since a project's"
        " settings name the plugin but do not download it: `claude plugin install sdlc@sdlc-marketplace --scope"
        " project`. `/sdlc:board` in a new session then prints the board.",
        protect,
        board,
        "5. Claim the first issue: open one labelled todo, run `claude` in your clone and paste: \"Claim issue N with"
        f" /sdlc:claim and carry it to a ready pull request, as {protocol} says. Where the skill names"
        " bash scripts/check.sh, run this repository's own checks instead. Do not merge.\"",
    ]


def next_steps_section(manifest):
    steps = next_steps_new(manifest) if manifest["mode"] == "new" else next_steps_existing(manifest)
    return [
        "## Next steps", "", *steps, "",
        "The same run makes the labels the board reads on this repository. Later releases of the protocol come from"
        " the public OpenSpineConsortium/sdlc-protocol: from a clone of it beside yours,"
        " `python3 ../sdlc-protocol/scripts/vendor.py . --consumer OpenSpineConsortium/sdlc-template`, by pull"
        " request.",
    ]


def render_body(manifest):
    lines = [opening(manifest), "", *changes_section(manifest), *notes_section(manifest),
             *sharing_section(manifest), *next_steps_section(manifest)]
    return "\n".join(lines).rstrip("\n") + "\n"


def command_body(options):
    try:
        manifest = json.loads(Path(options.manifest).read_text(encoding="utf-8"))
        if manifest.get("schema") != MANIFEST_SCHEMA:
            raise ValueError("not a manifest of this script")
        sys.stdout.write(title(manifest) + "\n" if options.title else render_body(manifest))
    except (OSError, ValueError, KeyError) as problem:
        print(f"adopt: {options.manifest}: {problem}", file=sys.stderr)
        return 1
    return 0


# --- labels -----------------------------------------------------------------------


def template_labels(template):
    """LABELS from the template's tools/template_init.py, read without
    running it, so the board's labels have one list."""
    script = init_script(Path(template).resolve())
    for node in ast.parse(script.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "LABELS" for t in node.targets):
            labels = ast.literal_eval(node.value)
            if all(len(label) == 3 and all(isinstance(part, str) and "\t" not in part and "\n" not in part
                                           for part in label) for label in labels):
                return [tuple(label) for label in labels]
    raise AdoptError(f"{INIT_SCRIPT} holds no list LABELS of (name, colour, description)")


def labels_for(template, mode):
    labels = template_labels(template)
    return labels if mode == "new" else [label for label in labels if label[0] not in TEAM_LABELS]


def command_labels(options):
    try:
        for label in labels_for(options.template, options.mode):
            print("\t".join(label))
    except (AdoptError, OSError, ValueError, SyntaxError) as problem:
        print(f"adopt: {problem}", file=sys.stderr)
        return 1
    return 0


# --- the command line -------------------------------------------------------------


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Adopt the OpenSpine SDLC template into a repository.")
    commands = parser.add_subparsers(dest="command", required=True)

    reading = commands.add_parser("parse", help="the adoption form's fields as KEY=value lines")
    reading.add_argument("body", nargs="?", help="the issue's body in a file (default: standard input)")

    applying = commands.add_parser("apply", help="copy the template into the target and write a manifest")
    applying.add_argument("--template", required=True, help="a checkout of the template")
    applying.add_argument("--target", required=True, help="a checkout of the repository that adopts it")
    applying.add_argument("--repo", required=True, help="the target's OWNER/NAME")
    applying.add_argument("--creator", required=True, help="the login of the person who asked")
    applying.add_argument("--owner-type", required=True, choices=OWNER_TYPES, help="the target owner's type")
    applying.add_argument("--default-branch", required=True, help="the target's default branch")
    applying.add_argument("--mode", required=True, choices=("new", "existing"))
    applying.add_argument("--metrics", required=True, choices=("on", "off"))
    applying.add_argument("--manifest", required=True, help="where to write the manifest, outside the target")
    applying.add_argument("--protocol-spec", help="sdlc-protocol's spec/PROTOCOL.md, which mode existing writes as"
                          " docs/agents/PROTOCOL.md; without it, the template's own page")

    body = commands.add_parser("body", help="the pull request's text from a manifest")
    body.add_argument("--manifest", required=True)
    body.add_argument("--title", action="store_true", help="print the title instead of the body")

    labels = commands.add_parser("labels", help="the board's labels as name<TAB>colour<TAB>description")
    labels.add_argument("--template", required=True)
    labels.add_argument("--mode", required=True, choices=("new", "existing"))
    return parser.parse_args(argv)


COMMANDS = {"parse": command_parse, "apply": command_apply, "body": command_body, "labels": command_labels}


def main(argv=None):
    options = parse_args(argv)
    return COMMANDS[options.command](options)


if __name__ == "__main__":
    sys.exit(main())
