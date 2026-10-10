"""Small trees for the tests: a fake template and the repositories that adopt it.

The fake template carries tests/fixtures/fake_init.py as its
tools/template_init.py: a stand-in written here, since this public
repository holds no file of the private template, so apply's subprocess
path runs for real while the real init is tested only behind SDLC_TEMPLATE
(tests/test_real_template.py). The placeholders are assembled at run time, as the
template's own tests do, so no file here carries one.
"""

import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

TESTS = Path(__file__).resolve().parent
FIXTURES = TESTS / "fixtures"
sys.path.insert(0, str(TESTS.parent / "scripts"))

import adopt  # noqa: E402

REPO = "octo-org/widget"
CREATOR = "mona"


def placeholder(name):
    return "{{" + name + "}}"


P = {name: placeholder(name) for name in ("PROJECT_NAME", "REPO", "OWNER", "CODE_OWNER", "DEFAULT_BRANCH", "YEAR")}

TEMPLATE_FILES = {
    ".template/PENDING": "This copy of the template has not been initialised.\n",
    ".claude/session.md": "# Session checkpoint\n\nThe template's own work in progress.\n",
    ".claude/settings.json": '{\n  "extraKnownMarketplaces": {}\n}\n',
    ".github/CODEOWNERS": f"* @{P['CODE_OWNER']}\n",
    ".github/workflows/board.yml": "name: Board\non:\n  push:\n",
    ".github/workflows/tidy.yml": "name: Tidy\non:\n  issues:\n",
    ".github/workflows/ci.yml": "name: Checks\non:\n  pull_request:\n",
    ".github/workflows/template-init.yml": "name: Template init\non:\n  push:\n",
    "CLAUDE.md": f"# {P['PROJECT_NAME']}\n\nThe template's instructions.\n",
    "README.md": f"# {P['PROJECT_NAME']}\n\nClone {P['REPO']}; the default branch is {P['DEFAULT_BRANCH']}.\n",
    "LICENSE": f"MIT License\n\nCopyright (c) {P['YEAR']} {P['OWNER']}\n",
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
SPEC = "# The claim protocol\n\nThe library's own text, with no placeholder.\n"

# The protocol's files mode existing adds to a repository that has none of them.
PROTOCOL_ADDED = {
    ".github/sdlc-metrics",
    ".github/workflows/board.yml",
    ".github/workflows/tidy.yml",
    "docs/agents/PROTOCOL.md",
    "docs/agents/claims/README.md",
    "tools/VENDORED",
    "tools/board.py",
    "tools/sdlc_protocol/__init__.py",
    "tools/sdlc_protocol/board.py",
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


def make_template(root, metrics=False, spec=False, only=None):
    """The fake template under root; with only, just those of its files."""
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
    if spec:
        write(root, adopt.PROTOCOL_SPEC, SPEC)
    return root


def make_target(root, files=None):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for rel, text in (files if files is not None else {"README.md": "# widget\n"}).items():
        write(root, rel, text)
    return root


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


def apply(template, target, manifest, mode="new", metrics="on", owner_type="User", repo=REPO):
    """Run apply; (exit code, the manifest or None, stderr)."""
    code, _, err = run([
        "apply", "--template", str(template), "--target", str(target), "--repo", repo,
        "--creator", CREATOR, "--owner-type", owner_type, "--default-branch", "main",
        "--mode", mode, "--metrics", metrics, "--manifest", str(manifest),
    ])
    written = json.loads(Path(manifest).read_text()) if code == 0 else None
    return code, written, err
