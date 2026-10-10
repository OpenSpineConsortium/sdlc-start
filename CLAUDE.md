# sdlc-start

This repository is the public front door to the OpenSpine SDLC template, OpenSpineConsortium/sdlc-template, which stays internal to its enterprise. A person fills in the form .github/ISSUE_TEMPLATE/adopt.yml, and .github/workflows/adopt.yml opens a pull request in their own repository, as the OpenSpine SDLC App, with the template or only its claim protocol; scripts/adopt.py does the reading and the copying. README.md says what each kind adds, what is shared and the owner's one-time setup.

## What must hold

- The template's repository is never exposed: no step prints its files, its history or its other branches, and its token is read-only and revoked right after the one checkout that uses it. Its files reach only the pull request in the requester's repository.
- An issue here is written by anyone, so everything in it is data. Values reach a shell step only through env:, never through an expression inside run:, and scripts/adopt.py parse refuses anything the form would not write; a message posted back never quotes the issue.
- Nothing lands in anyone's repository but a pull request they review. Mode existing never overwrites a file of theirs; LICENSE is never copied in either mode.
- What is shared is aggregates only, on by default and said so plainly in the form and the pull request, with one switch off: the file .github/sdlc-metrics.

## Checks

Run `bash scripts/check.sh` before opening or updating a pull request. CI runs the same script as the job named "check". It needs Python 3.12 (`PYTHON` names another interpreter).

## Writing

- Plain prose that says why, in comments, commit messages, pull requests and documents alike; what the code does is read from the code.
- Short functions; names that read as English.
- No emoji. ASCII and LF in every file, each ending with a newline.
- No new dependencies: Python 3.12 or later with its standard library, bash, gh, and GitHub's own actions plus actions/create-github-app-token@v1, pinned to a major tag. Tests use unittest. A proposal to add one is an issue first.
- Nothing refers to a file that does not exist.
- Never a real token or key in any file, test or example.

## Pushing

main takes only pull requests: never push to main and never force-push it. Work on a branch of your own and open a pull request from it.
