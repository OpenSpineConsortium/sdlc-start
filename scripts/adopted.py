#!/usr/bin/env python3
"""Say whether a repository has an adoption already, by the sweep's own rule.

The sweep (scripts/sweep.py) passes over a repository whose default branch
holds docs/agents/PROTOCOL.md, which every adoption from this front door
brings, in either kind, and every copy made with "Use this template"
carries; the installation's path of the form asks the same through
sweep.unadopted (scripts/resolve.py). A repository named on the form
reaches .github/workflows/adopt-run.yml by neither, and a second adoption
would put the template's files over the ones the repository has made its
own since (its CLAUDE.md and checkpoint, its README, its goal and memory,
its metrics switch), or, for the protocol alone, bring back what it has
taken out, so the run asks this before it reads the kind or stages a
file, on every path: one rule, sweep.is_adopted itself, for the three
ways a request arrives. scripts/adopt.py apply refuses an adoption that
could not write that file, so no adoption is made that the rule misses.

Exit 0 when the repository has no adoption yet, 3 when it has one, which
the run answers with one message that names nothing of it, 1 when GitHub
could not be asked, and 2 when GH_TOKEN is not set or the name is not one
scripts/adopt.py name would print. Nothing printed names the repository,
since the run's log is public and a repository given by ids may be
private. GH_TOKEN is the repository's installation token, which reads its
contents, and it is never printed. Python 3.12 or later, standard library
only.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import adopt  # noqa: E402
import sweep  # noqa: E402

ADOPTED = 3


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Whether a repository has an adoption already, by the sweep's rule.")
    parser.add_argument("repository", help="OWNER/NAME, as scripts/adopt.py name printed it")
    parser.add_argument("--api", default=sweep.API, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv=None, transport=sweep.urllib_transport):
    options = parse_args(argv)
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        print("adopted: GH_TOKEN is not set", file=sys.stderr)
        return 2
    try:
        adopt.parse_repository(options.repository)
    except adopt.FormError:
        print("adopted: the repository must be OWNER/NAME, as scripts/adopt.py name prints it", file=sys.stderr)
        return 2
    github = sweep.GitHub(token, transport, options.api)
    try:
        adopted = sweep.is_adopted(github, {"full_name": options.repository})
    except sweep.GitHubError as refusal:
        print(f"adopted: GitHub could not be asked ({refusal})", file=sys.stderr)
        return 1
    print("the repository is adopted already" if adopted else "the repository has no adoption yet")
    return ADOPTED if adopted else 0


if __name__ == "__main__":
    sys.exit(main())
