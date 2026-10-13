# Symphony GitHub Apps privacy statement

Version 5, 2026-10-13. This text is also at https://openspineconsortium.com/symphony/apps-privacy.html.
The Symphony browser extension has a statement of its own, at https://openspineconsortium.com/symphony/privacy.html.

Who makes the Apps: Gregory Schwing, trading as OpenSpineConsortium ("the developer"). Questions:
the contact on https://openspineconsortium.com/symphony/.

Symphony is two GitHub Apps. **SymphonyBoard** (github.com/apps/symphonyboard) brings the Symphony
template, or its claim protocol, into a repository by pull request, and afterwards reads one branch
of that repository once a day for anonymous aggregates. **Symphony Setup** (github.com/apps/symphony-setup)
applies up to six settings to a repository for one run and uninstalls itself. Both work only through
GitHub: nothing of yours goes anywhere but to GitHub's own API, to your own repository and, as
aggregates, to the developer. This statement says what each App can see, what it writes, what the
developer receives and keeps, and how to stop any of it.

## What each App asks for, and why

The unit of consent is the installation. Whatever repositories you give an App when you install it
("All repositories" or "Only select repositories"), the App can read what its permissions allow on
every one of them, and this statement applies to each.

SymphonyBoard asks for six repository permissions: Contents (read and write), to read your default
branch and push the branch `symphony/adopt`; Pull requests (read and write), to open the adoption
pull request and, only when you asked for it on the form, merge it; Issues (read and write), to
make the board's labels and, in a new repository, open the issue "Set up this project"; Checks (read
and write), to post the protocol check as a check run where the developer runs the App's server;
Workflows (read and write), because the pull request brings files under `.github/workflows`, which
GitHub lets no token write without it; and Metadata (read), which every App has, to list the
repositories it reaches. It subscribes to five event types (issues, issue comments, pull requests,
pushes and check suites), which GitHub delivers only while the App's webhook is turned on; as this
statement is written, it is turned off, and the section on the server below applies from the day
it is turned on. SymphonyBoard never asks for Administration.

Symphony Setup asks for two permissions and nothing else: Administration (read and write), for the
six settings below, and Metadata (read). It has no webhook and receives no event. It is meant to be
installed on the one repository being adopted, for the one run, and the run uninstalls it when that
repository was the only one it reached, after the adoption or after a request refused because the
repository is adopted already; otherwise the pull request, or that refusal's answer, asks you to
uninstall it.

## The adoption

Installing SymphonyBoard sends you on to Symphony Setup's install page, and that install
sends you to a public form on the front door repository,
github.com/OpenSpineConsortium/symphony-start. Pressing Create there opens a public issue in your
GitHub name; the issue carries what the form held (your installation's number, or a repository name
you typed, the kind, the merge choice and one box) and the run's answers, and it is closed when the run is done,
never deleted. A repository the run learns only by its number is never named on the front door: its
name, its owner's, its default branch's and your login are masked in the run's public log, and the
issue is answered with "your repository". A name you typed into the form is public already, and the
run names it in its answers. The front door's public logs do show the installation's number, the
repository's numeric id, the kind the run read (whether the repository was empty), how many files
it added, replaced, kept or skipped, and the commit ids of your default branch and of the template.

To do its work the run reads, from the repository being adopted: the default branch and the commit
on it, whether a branch `symphony/adopt` exists and has a pull request, whether `docs/agents/PROTOCOL.md`
exists, the one word in `.github/symphony-adopt` and `.github/symphony-metrics` and in each under
its name before the rename to Symphony, `.github/sdlc-adopt` and `.github/sdlc-metrics`, the full
listing of the default branch's tree (to decide the kind), a checkout of that branch at depth one (to add the
files), whether you administer the repository and, when the request came from the sweep below
rather than from you, the repository's direct collaborators and their permissions, to find an
administrator. With Symphony Setup installed, the run also reads the repository's rulesets, its
topics and its workflow permissions for GitHub Actions, to leave what is there as it is. Everything
read lives on GitHub's runner for the length of the run and goes with it; nothing of it is kept or
sent elsewhere.

What the run writes to your repository, as the App's bot: the board's labels, one commit on the
branch `symphony/adopt`, one pull request from it, and, in a repository that held nothing yet, the
issue "Set up this project". The pull request's body lists every file it brings, names the GitHub
login of the person who asked (or, from the sweep, the administrator it found), says whether the
repository is private and, where the Setup App was installed, quotes GitHub's own answer for each
setting, which may name your account's plan; in an organization's new repository, the pull request
also writes that login into `.github/CODEOWNERS`. With Symphony Setup installed, the run creates the
default branch's ruleset, turns on delete-head-branches and auto-merge, adds the topic `symphony` to
the repository's topics (the sign on the repository's page that it is adopted, which anyone can see
there and the Symphony browser extension reads from the page; your other topics stay), turns on
secret scanning and push protection where your plan and visibility allow it, and, in a repository
that takes the whole template, ticks "Allow GitHub Actions to create and approve pull requests" where
your organization and its enterprise allow it, then revokes the Setup App's token and uninstalls
the Setup App when the repository was its only one. Unless you chose on the form to review the pull request
first, the run merges it or arms auto-merge. Everything else lands only
when you merge. Closing the pull request instead leaves the labels, the branch, the settings, the
topic and the issue for you to undo. When the run could not open its pull request and nobody was on
the form to tell, the App opens one issue in your repository saying why.

The adoption's files come from the developer's private template repository, read with a token that
holds Contents read on that one repository and is revoked right after the checkout; only the files
in the pull request reach you.

## The sweep

Every ten minutes a workflow on the front door lists every installation of SymphonyBoard and, for
each installation older than half an hour whose owner has accepted every permission the pull
request needs, the repositories it reaches, and reads from each what the adoption reads to decide
whether to offer one: the default branch, the branches `symphony/adopt` and `sdlc/adopt`,
`docs/agents/PROTOCOL.md`, `.github/symphony-adopt` and `.github/sdlc-adopt`, closed pull requests
from `symphony/adopt`, and the App's own open issues. The sweep writes nothing itself; it starts the
adoption run above, by ids only, for a repository with no adoption yet. A repository that was
adopted, declined once (its pull request from `symphony/adopt` closed without a merge) or opted out
(`off` in `.github/symphony-adopt`) is passed over, but it is still read every ten minutes to learn
that; only uninstalling the App stops the reading. The sweep's own public log carries counts and
nothing else. The developer's own organization's repositories are never swept.

## Field metrics: what the developer receives

A repository Symphony set up runs its own workflow once a day, with GitHub's own token, which writes
one file, `METRICS.json`, to a branch named `metrics` of your repository: eleven counts (claims,
pull requests opened, merged, closed unmerged, reviews, changes requested, check runs passed and
failed, conflicts seen, released claims, contributors), the median and 90th percentile of three
waits in seconds, two rates, the time it was made, the number of days it covers (30), the protocol's
release number and the short id of its commit, and the words that name the schema and the switch.
Since version 2 of this statement the file also holds counts of how the work ran in parallel, so
that failure can be compared between one person running several Claude Code sessions at once and
several people working at once: seventeen counts of the people who opened pull requests, the Claude
Code sessions named on them, how many named one, the most pull requests, people and sessions of one
person at work at the same moment, the conflicts the board marked or GitHub reports on open pull
requests, and the pull requests the run could not read in full; for each of eight work settings
(nothing else at work beside it; one session's several pull requests; one person's several sessions;
several people; several people beside one person's several sessions; not known; the repository's own
Claude workflows; other apps and bots), thirteen counts and sums for the pull requests that ended in
the 30 days and those still open, such as how many merged, met a conflict or shared a changed file
with work beside them, and how long they were at work; and, for four kinds of pairs of pull requests
at work at the same time, seven counts of how many pairs there were and how many worked at once,
shared a file, had one land while the other was open, or met in conflict when it did. Since version
3 it also holds what the work cost, so that the cost of coordination can be measured: the date of
the price list the estimate uses; counts of the pull requests that ended in the 30 days, of those
merged and of those with any usage recorded against them, of the Claude Code sessions and the runs
of the repository's Claude workflows that recorded usage, and of the records left for a later run;
the tokens Claude used, by kind (input, cache writes, cache reads, output, in all, and those of a
model the price list does not know) and by model family (the fixed words fable, opus, sonnet, haiku
and other, never a model's name); what those tokens would cost at Anthropic's API list prices, in
dollars, and the part of it the coordinator workflow spent; the seconds Claude was at work; the
commits, failed checks and reverts of those pull requests; four of these per merged pull request;
and, for the pull requests done alone and those done with other work beside them, thirteen counts
and sums each (pull requests, merged, measured, measured and merged, tokens, dollars, seconds,
commits, failed checks, first checks passed and judged, the median wait from opening to merge, and
the time at work), with seven ratios between the two. To make the
file the workflow reads from GitHub's API, in its memory only and for the length of the run, the
pull requests changed in the 30 days and in the 30 before them, their commits, reviews, check runs
and changed files, the comments made or edited on the repository's issues and pull requests in
those 60 days, its branches and, for each claim branch with no pull request changed in the 30 days,
its newest commit; to sort the pull requests it uses the login of the person who opened each one, the
name of its branch, the Claude Code session link a cloud session writes into its commit messages and
pull request descriptions (and a line `Symphony-Session:` where a session writes one) and the times
of its commits, and to see whose files meet, the names of the files each changed; it writes none of
them. For what the work cost it reads two records the template's own tools leave in your
repository, never anything from the App: the line `Symphony-Usage:` that a Claude Code session of
the repository adds to each of its commit messages, holding token counts by model, the seconds the
session was at work and the first eight characters of the session's id, and no word of its
conversation; and the usage record each run of the repository's Claude workflows keeps as an
artifact of that run, holding token counts by model, seconds, turns, the workflow, the job and the
worker's name, and the issue and pull request the run was for, and nothing of the conversation.
It lists and downloads those artifacts with the repository's own token, from the last 60 days, and
keeps the records it has read in the repository's own Actions cache, so the next day's run reads
only the new ones. The file holds no name, login, session link or session id, title, branch name,
file name, link, issue number, model name, worker name, text or code; a test in the template fails
if any of those reaches the file.
Where a repository has few pull requests a count can describe a single one, and the counts say how a
project works, for instance that one person had three sessions' work going at once. The branch is as
visible as your repository. A maintainer of your project who chooses to run the template's judge on
their own computer, with their own Claude Code account, adds a second file, `JUDGE.json`, holding
counts of communication failure types, of the conversations it judged and of those that had two or
more people, in all and for each work setting, the totals of the failure types' three groups, the
number of pull requests it covered that ended in the 30 days, in each work setting, the number of
days it covered and any limit it ran under, the time it was made, which model and which version of its prompt it used, and the
word that names its schema; the App never runs that judge and only reads that file.

Once a day, at 04:17 UTC, the developer's collector lists the repositories every installation of
SymphonyBoard reaches (receiving from GitHub their names, owners and visibility, which it holds in
memory and never writes) and asks each for exactly those two files at the ref `metrics`, and for no
other path. It keeps a project's `METRICS.json` only when the file says sharing is on; otherwise
nothing of that project is stored and `JUDGE.json` is not read. Of each file it keeps a fixed list
of numbers, the time the file was made, the date of the price list and the few identifier-shaped
words named above; a value of another shape is dropped. The names of the work settings, of the kinds
of pairs, of the model families and of the two sides of the comparison are fixed words of the
template, the same in every repository's file, never words of your project. The developer
therefore learns, per repository and day, how the protocol performed in numbers, and nothing of what
the work was.

Each kept line names the repository only as a keyed hash (HMAC-SHA256) of its GitHub node id under a
secret the developer alone holds, derived from the App's private key or set separately, so the
developer can follow one repository's numbers from day to day, and across a rename or transfer,
without the dataset naming it; a reader of the dataset without that secret cannot tell which
repository a line is. Rotating the key or the secret gives every repository a new hash and ends the
thread. The dataset is a private branch of the developer's repository, one JSON line per repository
and day, with no expiry: lines are added beside earlier days', a second run on the same day replaces
that day's, and the branch's git history keeps every earlier version for as long as the branch
exists. It is read by the developer and by the collaborators on that private repository, for
research on how coordination fails and succeeds among Claude Code sessions; it is never sold and
never given to anyone else. The developer runs the collector on GitHub Actions; it talks to
api.github.com and nowhere else.

## Sharing is on by default, with three ways off

Sharing is on unless you turn it off: the adoption writes `on` into `.github/symphony-metrics`
unless you ticked the form's box "Do not share anonymous aggregates" or a switch of the repository's
own says `off` already, under that name or under `.github/sdlc-metrics`, its name before the rename
to Symphony, which the adoption never turns on; the sweep's adoptions write `on` on the same terms.
Where the switch cannot be written, because the repository ignores it or something of its own
stands where it goes, nothing the adoption brings shares: the protocol alone then brings no metrics
workflow, and the whole template's reads what stands in the switch's place as off. To turn
it off at any time: write `off` as the first word of `.github/symphony-metrics` on your default
branch (in a repository adopted before the rename, whose workflow reads only `.github/sdlc-metrics`,
write it there), or set the repository Actions variable `SDLC_METRICS` to `off` (and run the
workflow once, so the record on the branch says off), or uninstall SymphonyBoard, after which the
collector reaches nothing of yours. Disabling the workflow alone does not stop sharing, because the
branch keeps its last record and the collector reads it as that day's; turn the switch off first.
With the switch off the template's sessions also stop adding the `Symphony-Usage:` line to their
commits and its Claude workflows stop keeping usage records, and a person who wants no usage of
theirs on their commits whatever the repository says sets `SDLC_METRICS` to `off` in their own
environment. Lines already collected stay in the dataset under the hash; they carry nothing that
names you.

## The App's server, where it is run

SymphonyBoard's webhook server, when the developer turns the webhook on, receives from GitHub each
event the App subscribes to, acts on pull request events only (opened, synchronize, reopened, ready
for review, converted to draft, edited) and logs and ignores the rest. For a pull request event it
reads the action, the installation's id, the repository's full name and the pull request's number
from the delivery, then reads the pull request from the API (its head and base, its body, whether
it is a draft and its head commit) and whether the claim file for its issue exists at that commit,
and writes one thing: the check run `sdlc/protocol` on that commit, with a title and a summary that
lists each protocol problem in one line. It posts no comment. It verifies every delivery's signature
before reading it, keeps installation tokens in memory for at most an hour and stores nothing on
disk; its log holds one line per delivery with the time, the delivery's id, the event, the action,
the repository's full name, the duration and a short outcome, and never a token, a payload or a
person's words.

## Keys and tokens

Each App's private key is the developer's and is never given to anyone: it lives in the Actions
secrets of the developer's own repositories and in the server's environment, outside any
repository. Every token minted from it is an installation token that lives one hour, asked with the
fewest permissions the step needs (metadata alone to resolve a number, contents read to read, the
four write permissions only for the adoption itself) and revoked as soon as the step is done where
the code can. No token, key or signature is ever printed to a log.

## What the Apps never do

They send nothing to any service but GitHub's own API. They have no analytics, no error reporting
and no third party. SymphonyBoard never holds Administration on anyone's repository; Symphony Setup
holds it for one run and only where you installed it. They read your repository's code only as the
adoption above says (the tree listing, a one-commit checkout of the default branch, and the few
files named), never to keep or send it. They never write to a repository but the adoption's branch,
pull request, labels, issue and settings, each of them yours to undo, and the one issue that says a
pull request could not be opened. They never read a Claude credential, and nothing here runs on
anyone's Claude account but the one a project's own maintainer chooses to run the judge with.

## Uninstalling

Uninstalling SymphonyBoard stops the sweep and the collector from reading anything of yours and
undoes nothing in your repository: the files, labels, branch, settings and issues the adoption made
stay yours. Uninstalling Symphony Setup is what you do once the pull request is open, when the run
did not do it for you.

## Children

Symphony is for people who administer GitHub repositories. It is not directed at children.

## Changes

A new version of this statement is published at https://openspineconsortium.com/symphony/apps-privacy.html
and in the front door repository, github.com/OpenSpineConsortium/symphony-start, whose PRIVACY.md is
this text.

Version 5 says that the run also reads the two switches under their names before the rename to
Symphony, `.github/sdlc-adopt` and `.github/sdlc-metrics`; that an adoption never turns on a switch
of the repository's own that says off already, under either name, and brings nothing that shares
where it cannot write the switch; that a repository adopted before the rename turns sharing off in
`.github/sdlc-metrics`, the switch its workflow reads; and that Symphony Setup also uninstalls
itself after a request refused because the repository is adopted already. Nothing the developer
receives or keeps changed.

Version 4 adds the sixth setting Symphony Setup applies: in a repository that takes the whole
template, it ticks "Allow GitHub Actions to create and approve pull requests" where your
organization and its enterprise allow it. It also names what the run reads to leave your settings as
they are: the repository's rulesets, its topics and its workflow permissions for GitHub Actions.
Nothing the developer receives or keeps changed.

Version 3 adds to `METRICS.json` what the work cost, as the section on field metrics describes: the
tokens Claude used, by kind and by model family, their price at Anthropic's API list prices and the
date of that list, the seconds Claude was at work, the counts and rates per merge they are set
against, and the comparison of work done alone with work done in parallel; and it says which
records in your repository the workflow reads to make them, and that the switch stops those records
too. Nothing else changed.

Version 2 adds to `METRICS.json` and `JUDGE.json` the counts of how the work ran in parallel that
the section on field metrics describes, and to `JUDGE.json` how many of its conversations had two or
more people, the number of days it covered and any limit it ran under. It also says what the
workflow reads to make `METRICS.json`, and names what the two files held already and version 1 left
out: the time each was made, the number of days `METRICS.json` covers and the short id of the
protocol's commit, and, in `JUDGE.json`, how many conversations were judged, the totals of the
failure types' three groups, the model, the version of the prompt and the word that names its
schema. Nothing else changed.

Symphony is not a GitHub or Anthropic product. "GitHub" is GitHub's mark; "Claude" and "Claude Code"
are Anthropic's marks, used here to say what Symphony works with.
