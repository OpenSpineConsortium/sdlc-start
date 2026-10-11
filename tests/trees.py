"""Small trees for the tests: a fake template and the repositories that adopt it.

The fake template carries tests/fixtures/fake_init.py as its
tools/template_init.py: a stand-in written here, since this public
repository holds no file of the private template, so apply's subprocess
path runs for real while the real init is tested only behind SDLC_TEMPLATE
(tests/test_real_template.py). The placeholders are assembled at run time, as the
template's own tests do, so no file here carries one. Every file's content
stands in for the template's and quotes none of it: a test checks that a
file is there, filled, kept or gone, never the template's own words.
"""

import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

TESTS = Path(__file__).resolve().parent
FIXTURES = TESTS / "fixtures"
sys.path.insert(0, str(TESTS.parent / "scripts"))

import adopt  # noqa: E402

REPO = "octo-org/widget"
CREATOR = "mona"
MARK_BEGIN = "<!-- cswap:checkpoint:begin -->"
MARK_END = "<!-- cswap:checkpoint:end -->"
# What both lists of the checkpoint block read once the init has emptied them.
EMPTY_LISTS = {"Durable decisions": ["- (none recorded)"], "Constraints": ["- (none recorded)"]}


def placeholder(name):
    return "{{" + name + "}}"


P = {name: placeholder(name) for name in ("PROJECT_NAME", "REPO", "OWNER", "CODE_OWNER", "DEFAULT_BRANCH", "YEAR")}

# The template's CLAUDE.md ends in the checkpoint block, holding its own lists.
TEMPLATE_CLAUDE = (
    f"# {P['PROJECT_NAME']}\n\nThe template's instructions.\n\n"
    f"{MARK_BEGIN}\n## Session checkpoint (kept by cswap)\n\nRead `.claude/session.md` at the start of a session.\n\n"
    "### Durable decisions\n- The template's own decision.\n### Constraints\n- The template's own constraint.\n"
    f"{MARK_END}\n"
)

TEMPLATE_FILES = {
    ".template/PENDING": "marker\n",
    ".claude/session.md": "# Session checkpoint\n\nThe template's own work in progress.\n",
    ".claude/settings.json": '{\n  "extraKnownMarketplaces": {}\n}\n',
    ".github/CODEOWNERS": f"* @{P['CODE_OWNER']}\n",
    ".github/workflows/board.yml": "name: Board\non:\n  push:\n",
    ".github/workflows/tidy.yml": "name: Tidy\non:\n  issues:\n",
    ".github/workflows/ci.yml": "name: Checks\non:\n  pull_request:\n",
    ".github/workflows/template-init.yml": "name: Template init\non:\n  push:\n",
    "CLAUDE.md": TEMPLATE_CLAUDE,
    "README.md": f"# {P['PROJECT_NAME']}\n\nClone {P['REPO']}; the default branch is {P['DEFAULT_BRANCH']}.\n",
    "LICENSE": "a license file the adoption never copies\n",
    "docs/agents/PROTOCOL.md": f"# How work is claimed\n\nThe queue is on {P['REPO']}; pushes to {P['DEFAULT_BRANCH']}.\n",
    "docs/agents/claims/README.md": f"# Claim files\n\n- Issue: https://github.com/{P['REPO']}/issues/N\n",
    "docs/setup/github.md": "# GitHub settings\n",
    "tools/VENDORED": "sdlc-protocol 0.0.0 0000000000000000000000000000000000000000\n",
    "tools/board.py": "print('the board')\n",
    "tools/sdlc_protocol/__init__.py": "__version__ = '0.0.0'\n",
    "tools/sdlc_protocol/board.py": "def render():\n    return ''\n",
    "tools/sdlc_protocol/__pycache__/board.cpython-312.pyc": "not a real cache\n",
    "tests/test_template.py": "import unittest\n",
    "scripts/check.sh": "#!/usr/bin/env bash\necho ok\n",
    ".git/config": "[core]\n\tbare = false\n",
}
EXECUTABLE = ("scripts/check.sh",)
METRICS = {
    ".github/workflows/metrics.yml": "name: Metrics\non:\n  schedule:\n",
    "tools/metrics.py": "print('metrics')\n",
}
# The library's spec/PROTOCOL.md, which the workflow passes as --protocol-spec.
SPEC = "# The claim protocol\n\nThe library's own text, with no placeholder.\n"
LIBRARY = ("tools/VENDORED", "tools/sdlc_protocol/__init__.py", "tools/sdlc_protocol/board.py")

# The protocol's files mode existing adds to a repository that has none of them.
PROTOCOL_ADDED = {
    ".github/sdlc-metrics",
    ".github/workflows/board.yml",
    ".github/workflows/tidy.yml",
    "docs/agents/PROTOCOL.md",
    "docs/agents/claims/README.md",
    *LIBRARY,
    "tools/board.py",
}

THEIR_CLAUDE = "# Widget\n\nOur own rules for sessions.\n"
THEIR_SETTINGS = {"permissions": {"allow": ["Bash(make test)"]}, "model": "opus"}
# Written by hand, as a person would, so a merge that reflowed it would show.
THEIR_SETTINGS_TEXT = '{\n    "permissions": {"allow": ["Bash(make test)"]},\n    "model": "opus"\n}\n'
THEIR_FILES = {
    "CLAUDE.md": THEIR_CLAUDE,
    ".claude/settings.json": THEIR_SETTINGS_TEXT,
    "README.md": "# Widget\n\nIt makes widgets.\n",
    "tests/test_widget.py": "import unittest\n\n\nclass Widget(unittest.TestCase):\n    pass\n",
    ".github/workflows/ci.yml": "name: CI\non:\n  push:\n",
    ".git/HEAD": "ref: refs/heads/main\n",
}


def write(root, rel, data):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return path


def make_template(root, metrics=False, only=None):
    """The fake template under root; with only, just those of its files. Its
    vendored copy carries no spec, as the real one does not."""
    root = Path(root)
    for rel, text in TEMPLATE_FILES.items():
        if only is None or rel in only:
            write(root, rel, text)
    for rel in EXECUTABLE:
        if (root / rel).exists():
            os.chmod(root / rel, 0o755)
    write(root, adopt.INIT_SCRIPT, (FIXTURES / "fake_init.py").read_bytes())
    for rel in (METRICS if metrics is True else metrics or ()):
        write(root, rel, METRICS[rel])
    return root


def make_target(root, files=None):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for rel, text in (files if files is not None else {"README.md": "# widget\n"}).items():
        write(root, rel, text)
    return root


def make_checkout(root, files, ignore):
    """A git checkout under root with files and these ignore rules, so what
    the repository ignores is read for real; a plain folder ignores nothing."""
    make_target(root, dict(files, **{".gitignore": ignore}))
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    return root


def track(root, rel):
    """Put rel in the checkout's index, as a committed file of theirs is."""
    subprocess.run(["git", "-C", str(root), "add", "-f", rel], check=True, capture_output=True)


def snapshot(root):
    """Every regular file under root, .git included, as relative path -> bytes."""
    root = Path(root)
    found = {}
    for folder, dirs, names in os.walk(root):
        for name in names:
            path = Path(folder) / name
            if not path.is_symlink():
                found[path.relative_to(root).as_posix()] = path.read_bytes()
    return found


def checkpoint_lists(text):
    """The lists of CLAUDE.md's checkpoint block, heading -> its lines; None
    when the file has no block."""
    begin, end = text.find(MARK_BEGIN), text.find(MARK_END)
    if begin == -1 or end == -1:
        return None
    lists, current = {}, None
    for line in text[begin:end].replace("\r\n", "\n").split("\n"):
        if line.startswith("### "):
            current = line[4:].strip()
            lists[current] = []
        elif current is not None and line.strip():
            lists[current].append(line.rstrip())
    return lists


def run(argv, stdin=None):
    """adopt.main with its output caught: (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    saved = sys.stdin
    if stdin is not None:
        sys.stdin = io.StringIO(stdin)
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = adopt.main(argv)
    finally:
        sys.stdin = saved
    return code, out.getvalue(), err.getvalue()


def apply(template, target, manifest, mode="new", metrics="on", owner_type="User", repo=REPO, protocol_spec=None,
          source=None, creator=CREATOR, kind_read=False):
    """Run apply; (exit code, the manifest or None, stderr)."""
    argv = [
        "apply", "--template", str(template), "--target", str(target), "--repo", repo,
        "--creator", creator, "--owner-type", owner_type, "--default-branch", "main",
        "--mode", mode, "--metrics", metrics, "--manifest", str(manifest),
    ]
    if protocol_spec is not None:
        argv += ["--protocol-spec", str(protocol_spec)]
    if source is not None:
        argv += ["--source", source]
    if kind_read:
        argv.append("--kind-read")
    code, _, err = run(argv)
    written = json.loads(Path(manifest).read_text()) if code == 0 else None
    return code, written, err
