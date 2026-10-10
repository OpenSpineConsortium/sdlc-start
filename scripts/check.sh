#!/usr/bin/env bash
# The front door's checks, run by CI (.github/workflows/ci.yml, the job
# "check") and by hand before a pull request. Every text file comes first:
# the workflow and the form are read by GitHub and the script's output
# lands in other people's repositories, so a stray byte or a carriage
# return here becomes one there. Then the tests, on Python 3.12, the oldest
# Python the scripts promise; PYTHON names another interpreter. Then
# actionlint on the workflows, where it is on PATH: the runner has none, so
# it runs wherever the checks are run with it installed.
set -eu
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python3.12}"

"$PYTHON" - <<'EOF'
"""One line per file that is not plain ASCII with LF endings and a final
newline; exit 1 if there is any. The files are git's: tracked ones and new
ones that are not ignored."""
import subprocess
import sys

listed = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                        capture_output=True, check=True).stdout
problems = []
for name in sorted({n.decode() for n in listed.split(b"\0") if n}):
    try:
        data = open(name, "rb").read()
    except FileNotFoundError:
        continue  # removed from the working tree, still in the index
    if any(byte > 127 for byte in data):
        problems.append(f"{name}: a byte outside ASCII")
    if b"\r" in data:
        problems.append(f"{name}: a carriage return; use LF line endings")
    if data and not data.endswith(b"\n"):
        problems.append(f"{name}: no newline at the end")
print("\n".join(problems) or "plain text ok")
sys.exit(1 if problems else 0)
EOF

bash -n scripts/refuse.sh

"$PYTHON" -m unittest discover -s tests -v

if command -v actionlint >/dev/null 2>&1; then
  actionlint
  echo "actionlint ok"
else
  echo "actionlint is not on PATH; skipped"
fi

echo "checks ok"
