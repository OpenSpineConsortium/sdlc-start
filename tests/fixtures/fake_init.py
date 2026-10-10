"""A stand-in for the template's tools/template_init.py, written here.

The template is private, so this public repository carries none of its
files. This stand-in does what scripts/adopt.py relies on the real init
for, and no more: it takes the same arguments, fills the placeholders in
every text file outside .git, .github/workflows and .template, names the
person who made an organization's copy as its code owner, deletes the
marker folder .template and writes a blank .claude/session.md. It also
holds a LABELS list in the shape adopt.py reads. The tests that run the
real init are in tests/test_real_template.py, behind SDLC_TEMPLATE.
"""

import argparse
import json
import shutil
from pathlib import Path

LABELS = (
    ("todo", "0e8a16", "Ready to be claimed"),
    ("claimed", "fbca04", "Someone holds the claim"),
    ("in-review", "1d76db", "Waiting for review"),
    ("blocker", "b60205", "Holds everything up"),
    ("account:main", "5319e7", "For the main account"),
    ("epic", "8b5cf6", "Planned into tasks by a lead"),
    ("blocked", "e99695", "Waiting on someone else"),
)
BLANK = "# Session checkpoint\n\nNothing has been checkpointed yet.\n"
SKIPPED = (".git", ".template")


def marker(name):
    return "{{" + name + "}}"


def code_owner(repo, event_path):
    owner = repo.split("/")[0]
    event = json.loads(Path(event_path).read_text(encoding="utf-8")) if event_path else {}
    in_organization = event.get("repository", {}).get("owner", {}).get("type") == "Organization"
    return event.get("sender", {}).get("login", owner) if in_organization else owner


def skipped(rel):
    return rel.parts[0] in SKIPPED or tuple(rel.parts[:2]) == (".github", "workflows")


def fill_tree(root, values):
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file() or skipped(path.relative_to(root)):
            continue
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue
        filled = text
        for name, value in values.items():
            filled = filled.replace(marker(name), value)
        if filled != text:
            path.write_bytes(filled.encode("utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--default-branch", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--event", default="")
    parser.add_argument("--year", default="2026")
    args = parser.parse_args()
    root = Path(args.root)
    owner, name = args.repo.split("/")
    fill_tree(root, {"PROJECT_NAME": name, "REPO": args.repo, "OWNER": owner, "YEAR": args.year,
                     "CODE_OWNER": code_owner(args.repo, args.event), "DEFAULT_BRANCH": args.default_branch})
    shutil.rmtree(root / ".template", ignore_errors=True)
    (root / ".claude").mkdir(exist_ok=True)
    (root / ".claude" / "session.md").write_text(BLANK, encoding="utf-8")


if __name__ == "__main__":
    main()
