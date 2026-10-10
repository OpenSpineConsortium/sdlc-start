# sdlc-start

The front door to the OpenSpine SDLC template: one form here, and a pull request lands in your own repository with the template, or only its claim protocol, filled in with your names. The template's repository stays private; the files in the pull request are yours.

## Adopt it in three steps

1. **Install the App** on your repository: https://github.com/apps/openspine-sdlc/installations/new. Choose "Only select repositories" and pick the one repository. You must be an administrator of it, and it needs at least one commit (a README is enough).
2. **Open the form**: https://github.com/OpenSpineConsortium/sdlc-start/issues/new?template=adopt.yml. Name the repository as OWNER/NAME, choose the kind, leave or change the metrics choice, tick the box.
3. **Review and merge the pull request it opens** in your repository, from the branch sdlc/adopt. The issue here is answered with a link to your repository's pull requests and closed. The pull request lists every file it adds, keeps or replaces, and the steps that are left.

The run makes the board's labels in your repository at once, pushes the branch sdlc/adopt and, for a new repository, opens the issue "Set up this project" there; everything else lands only when you merge. You can close the pull request instead, which leaves those labels, that branch and that issue for you to delete or close. Uninstalling the App afterwards undoes nothing in your repository; it only stops the metrics below from being read.

## What each kind adds

**New repository: the whole template**, as "Use this template" would make it: the instructions and rules every Claude Code session reads (CLAUDE.md, .claude/), the shared memory, the board and its workflows, the checks, team mode's workflows, the setup scripts and the documents, with the placeholders filled with your repository's names, the template's marker folder removed and a blank session checkpoint. The template's own init does the filling, so the copy is the one GitHub would have made. A file your repository has already that the template also has, typically the README GitHub made, is replaced, and the pull request lists it; files the template does not have are left alone. The run also makes the board's labels and opens the issue "Set up this project" in the repository, as the template's own init does after "Use this template", since the copy's README and its setup pages send you to that issue; when it cannot be opened, the answer here says so, and the pull request's next steps and docs/setup/owner-checklist.md stand in for it. Afterwards `bash scripts/setup-repo.sh` sets up the GitHub side (or `python3 scripts/crowd.py setup` for a project worked by volunteers on their own Claude accounts); the pull request says so.

**Existing repository: the protocol only**, the files a person would otherwise copy by hand, so the template's tests, checks and documents never meet yours:

- tools/sdlc_protocol/ and tools/VENDORED, the claim protocol's library as the template vendors it, with tools/board.py;
- .github/workflows/board.yml, which keeps the board on the branch `board`, and .github/workflows/tidy.yml, which deletes a closed issue's claim branch;
- docs/agents/PROTOCOL.md, the protocol in prose, which is the public sdlc-protocol's own spec/PROTOCOL.md at the release the template vendors, and docs/agents/claims/README.md;
- a section "How work is claimed" at the end of your CLAUDE.md (or a new CLAUDE.md with it), which imports the protocol into every session;
- two keys in .claude/settings.json, `extraKnownMarketplaces` and `enabledPlugins`, which name OpenSpineConsortium/sdlc-marketplace and enable its plugin sdlc (the skills, /sdlc:board and the push guard); every key your file has stays, and a file that is not valid JSON is left alone and the pull request says so;
- the board's labels, made by the run at once.

No file of yours is overwritten: one that is there already is kept and listed as kept. What is left by hand, each person installing the plugin once and protecting the default branch, is in the pull request.

Both kinds write `.github/sdlc-metrics`, the metrics switch below, and bring the template's metrics workflow once the template carries it. Neither copies LICENSE: licensing your project is your decision.

## What is shared, and how to turn it off

By default a repository that adopts the template shares anonymous aggregates of the protocol at work, so it can be measured in real projects: counts (claims, pull requests opened, merged and closed, reviews, check runs passed and failed, conflicts, released claims, contributors as a number), durations (medians and 90th percentiles from claim to pull request, from opening to merge, to the first review), rates (merge rate, first-check pass rate) and, when a maintainer runs the judge, failure-type frequencies. Never code, text, titles, logins, branch names or repository names. Your repository's own workflow computes the counts, the durations and the rates and writes them to the file METRICS.json on its branch `metrics`. Failure-type frequencies come only from JUDGE.json on that branch, which exists only when a maintainer runs the judge (`python3 tools/metrics.py judge`) on their own machine and their own Claude account, and which holds category counts and nothing else. The App reads METRICS.json and JUDGE.json on the branch `metrics` and nothing else, and the dataset names your repository only by a salted hash. That workflow comes with the template; until the template carries it, an adoption records the switch and nothing is computed or shared.

To turn it off, at any time: choose "Do not share" in the form; or write `off` in `.github/sdlc-metrics` on your default branch; or set the repository variable SDLC_METRICS to `off`. Uninstalling the App stops it too. While it is off, the workflow writes only that sharing is off.

## The template stays private

OpenSpineConsortium/sdlc-template is internal to its enterprise, and adopting it does not change that. The App reads it inside this repository's workflow, with a read-only token that is revoked as soon as the files are read, and writes them into a pull request in your repository.

What that means: the files in the pull request are yours to read, change and keep, in a private repository or a public one, and nothing about them is hidden from you. What it does not mean: access to the template's repository itself, its history, its issues, its pull requests or its other branches, none of which leave the run; and no later change reaches your repository by itself. Later releases of the protocol come from the public OpenSpineConsortium/sdlc-protocol, by its scripts/vendor.py and a pull request of your own, as the pull request's last lines say.

This repository is public, and so is everything on its issues: the repository name you type in the form, and the workflow run that handles it, are visible to anyone. If a private repository's name says more than you want to show, keep the issue's title a throwaway description; the name in the form still shows. Until a request passes the run's checks, its log shows only whether the account you name has installed the App, and nothing about the repository itself: a repository the App does not reach and an author who is not one of its administrators get the same answer. A request that passes shows what the run did there, as any run does, which is the name of your default branch and the labels it made; the files it staged, git's own messages, the names of your other branches and the number of any pull request or issue in your repository are never printed.

## How it works

- .github/ISSUE_TEMPLATE/adopt.yml, the form, labels its issue `adopt`.
- .github/workflows/adopt.yml runs on that issue: it reads the form, makes the App's token for the account that owns your repository and checks with it, silently, that the App reaches the repository and that the issue's author is one of its administrators, makes the token that writes there, reads the template with a read-only token, in mode existing fetches the protocol's page from the public OpenSpineConsortium/sdlc-protocol at the release the template vendors, runs scripts/adopt.py on a checkout of your repository, commits on the branch sdlc/adopt as the App, opens the pull request, makes the labels and, in mode new, opens the setup issue. Its header says why each step is as it is.
- scripts/adopt.py does the reading and the copying: `parse` checks the form, `apply` copies the files and writes a manifest of them, `body` writes the pull request's text from the manifest, `labels` reads the board's labels from the template's own list.
- scripts/refuse.sh answers a request that ends without a pull request: it says why on the issue and closes it.

## For the owner

One-time setup, by an owner of OpenSpineConsortium, before the form works. The label comes first: GitHub applies a form's label only when the label exists, and the workflow runs only on an issue that carries it, so a request opened before the label exists starts no run, is never answered and has to be opened again once the label is there. From then on, until the variable and the secret below are set, every request is answered that the front door is not set up yet, and stays open.

1. **Make the label the form applies**:

   ```bash
   gh label create adopt --repo OpenSpineConsortium/sdlc-start --color 0e8a16 --description "A request for an adoption pull request, handled by .github/workflows/adopt.yml"
   ```

2. **Make the App public**, so accounts outside the organization can install it: https://github.com/organizations/OpenSpineConsortium/settings/apps/openspine-sdlc/advanced, "Make public".
3. **Give the App the permission Workflows: Read and write**: https://github.com/organizations/OpenSpineConsortium/settings/apps/openspine-sdlc/permissions, Repository permissions, Workflows. The pull request adds files under .github/workflows/, which GitHub lets an App write only with it. The run asks the App for a token with Contents, Pull requests, Issues and Workflows as Read and write, and Metadata as Read-only, for the one repository; the App has the first three already, and Workflows is new. Every existing installation, the organization's own included, then has to accept the new permission (the installation's page shows a review request) before it takes effect; a request for a repository whose installation has not accepted it is refused with a note that says so.
4. **Check the App's installation on OpenSpineConsortium includes sdlc-template**: https://github.com/organizations/OpenSpineConsortium/settings/installations, OpenSpine SDLC, Configure, Repository access. The App need not be installed on this repository: every answer here is posted with the workflow's own token.
5. **Give this repository the App's id and private key**, as the variable SDLC_APP_ID (https://github.com/OpenSpineConsortium/sdlc-start/settings/variables/actions) and the secret SDLC_APP_PRIVATE_KEY (https://github.com/OpenSpineConsortium/sdlc-start/settings/secrets/actions). From a clone, with the key file the App's settings page generated; gh reads the key from the file and nothing prints it:

   ```bash
   gh variable set SDLC_APP_ID --repo OpenSpineConsortium/sdlc-start --body 5258276
   gh secret set SDLC_APP_PRIVATE_KEY --repo OpenSpineConsortium/sdlc-start < openspine-sdlc.private-key.pem
   ```

   Anyone who can push to this repository can reach that key through a workflow, so keep write access here to the organization's owners. A key that is set but wrong, or an id that is, gets every request the answer that the front door's App is not working, leaves the issue open and ends the run red, so that it is seen here.
6. **Protect main**: require a pull request and the check named "check" (.github/workflows/ci.yml), and block force pushes and deletions, at https://github.com/OpenSpineConsortium/sdlc-start/settings/rules.

There is no LICENSE file here, and the adoption copies none into anyone's repository: what license, if any, the template's files are offered under is the owner's decision, and adding a LICENSE here is a pull request once it is made.

## Checks

`bash scripts/check.sh` holds every file to ASCII with LF endings and a final newline and runs the tests on Python 3.12 (`PYTHON=python3 bash scripts/check.sh` takes another interpreter), and actionlint on the workflows when it is on PATH. CI runs the same script as the job named "check". The tests that run apply against the real template skip unless SDLC_TEMPLATE names a checkout of it, and CI here cannot read the template, so whoever can runs `SDLC_TEMPLATE=/path/to/sdlc-template bash scripts/check.sh` before a change to scripts/adopt.py merges.
