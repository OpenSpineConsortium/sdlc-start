# sdlc-start

This repository is the public front door to the OpenSpine SDLC template, OpenSpineConsortium/sdlc-template, which stays internal to its enterprise. A person fills in the form .github/ISSUE_TEMPLATE/adopt.yml, and .github/workflows/adopt.yml checks it and calls .github/workflows/adopt-run.yml, which opens a pull request in their own repository, as the OpenSpine SDLC App, with the template or only its claim protocol; or they only install the App, and .github/workflows/sweep.yml finds the repository within the hour and starts the same run by dispatch, with the installation's and the repository's ids and never a name; scripts/adopt.py does the reading and the copying. README.md says what each kind adds, what is shared and the owner's one-time setup.

## What must hold

- The template's repository is never exposed: no step prints its files, its history or its other branches, and its token is read-only and revoked right after the one checkout that uses it. Its files reach only the pull request in the requester's repository.
- An issue here is written by anyone, so everything in it is data. Values reach a shell step only through env:, never through an expression inside run:, and scripts/adopt.py parse refuses anything the form would not write; a message posted back never quotes the issue. A repository the sweep found may be private and was named on no issue: its name reaches no log, no run input, no step output and no job summary; the run resolves the ids with a metadata-only token and masks the name, its owner's and the requester's login before anything prints them.
- Nothing lands in anyone's repository but a pull request they review, apart from three things the run makes at once and the form says it makes: the board's labels, the branch sdlc/adopt and, in mode new, the issue "Set up this project"; and, on the sweep's path alone, the one issue "OpenSpine SDLC could not open its pull request" when the run could not, which the sweep reads as told. Mode existing never overwrites a file of theirs; LICENSE is never copied in either mode. The sweep offers nothing to a repository that declined (a closed pull request from sdlc/adopt) or opted out (`off` in .github/sdlc-adopt), nor to the organization's own repositories.
- What is shared is aggregates only, on by default and said so plainly in the form and the pull request, with one switch off: the file .github/sdlc-metrics.

## Checks

Run `bash scripts/check.sh` before opening or updating a pull request. CI runs the same script as the job named "check". It needs Python 3.12 (`PYTHON` names another interpreter). The tests in tests/test_real_template.py skip unless SDLC_TEMPLATE names a checkout of the template, which CI cannot read, so whoever can runs `SDLC_TEMPLATE=/path/to/sdlc-template bash scripts/check.sh` before a change to scripts/adopt.py merges.

## Writing

- Plain prose that says why, in comments, commit messages, pull requests and documents alike; what the code does is read from the code.
- Short functions; names that read as English.
- No emoji. ASCII and LF in every file, each ending with a newline.
- No new dependencies: Python 3.12 or later with its standard library, bash, gh, and GitHub's own actions plus actions/create-github-app-token@v1, pinned to a major tag. Tests use unittest. A proposal to add one is an issue first.
- Nothing refers to a file that does not exist.
- Never a real token or key in any file, test or example.

## Pushing

main takes only pull requests: never push to main and never force-push it. Work on a branch of your own and open a pull request from it.
