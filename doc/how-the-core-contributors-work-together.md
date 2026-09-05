# How we work together

The core contributors are multiple teams with different strengths and areas of expertise/focus,
collaborating together remotely and asynchronously. These are some basic practices that
we use to work effectively without tripping over each other.

## Areas of focus for each sub-team

We cross over and help each other out where we can, but these are our core areas:

*SINTEF*: Domain knowledge, core algorithms, core/backend functionality

*SINTEF Digital*: TODO

*IFE*: User experience, frontend implementation

*RISE*: Domain knowledge, core/backend algorithms

*STATNETT/UNICUS*: End to end architecture, integration, overall developer experience

## Communication norms

Its a good idea to keep a running conversation between us. These are the primary ways we keep each other in the loop:

- "Ongoing" text chat
- Descriptive writing to each other in pull requests (see git tips below)
- If we need to do focused problem solving/knowledge sharing across the sub-teams, we set up video calls ad-hoc as needed

_TODO some clarification about how teams resolve shared tasks/dependencies, task tracking etc_

_TODO Need to set up that shared Teams chat in a way that works for Statnett project_

## Git workflow, mandatory bits

These are the minimum things we need to do to not trip over each other:

- **`main` branch is protected**, eg. you cannot push commits directly to it

- Instead, **use feature branches, and create pull requests** to merge your code into main

- **We do not require other people to approve your branches before you merge**.
However, we have some automated tests and checks. If your branch breaks any of these,
you will not be able to merge until those are fixed in your branch.

## "git hygiene", collaboration tips

A few additional tips to consider:

- **Consider writing up a little description/context in every pull request.** Even if you are only working alone on a section of the project, writing up some sentences of description in each pull request
to teach the rest of us what you are working on/towards. Sometimes others may be able to give tips and advice, too :)

- **If you are working on a large chunk of functionality/code, it does not have to go in with a single big bang pull request.**
If possible, try to split it into multiple self-contained PRs(as long as it does not break things for others along the way).
Integrating back into `main` often helps you avoid surprises and code merge conflicts.

- **If you need/want to keep your feature branch more long lived, it is a good idea to rebase it from the main branch daily.**
Eg. switch to main branch, pull the latest changes to it, go back to your own branch, run `git rebase main`.
This in effect "redoes" your branch so that it looks as if you
branched it off of the latest version of `main`. If you have been working on the same places in the repo as others, you may get some conflicts when you do this.
However its much easier to resolve these conflicts early and often rather than after a week or two of steady work!

- **We kindly suggest using _"squash and merge"_ when you merge pull requests.** (If that is not what the green merge button already says in your pull request,
  then try clicking the little dropdown button on its right side and you should find the squash option).
  This makes each of your pull requests merge into main as a single atomic commit, which makes the main branch easier to reason about if anything goes wrong :)

- **There is a `CODEOWNERS` file at the top of the repo, listing who owns which parts of the code.**
When your branch touches somebody's files, GitHub adds them as a reviewer on your pull request automatically.
This does not block you from merging, it just makes sure Github notifies the right people about the change. The header
comment in `CODEOWNERS` explains the details, and tells you how to add yourself if you "own" an area the repo.

## Always keep the repo testable/runnable locally

**The main branch should always be runnable** Eg. anytime we merge something to main,
the project overall should still be in a state where it can be launched and tested fully by anyone.

**When you introduce new functionality, we highly suggest you include some unit tests** that automate regression testing. Eg.
if breaks later on, an automated test should be able to catch it. If some test is very hard to automate,
ask the rest of the projects participants for ideas! If the functionality is still truly hard to automate testing,
a fallback can be to at least write a .md checklist about how that service/component/part can be tested manually.

**Any additional services need to be defined in docker compose for local testing** If/when we introduce more subprocesses, services etc, make sure they are defined both in the kubernetes deployments as well as the
local docker compose file for local testing, so it is replicated in some way locally. If you introduce some infrastructure that only "truly work" in the deployed cloud env, we should also make sure that it remains
testable locally for example via synthetic data, stubs/mocks etc.

## Do not put any secrets in this repo

**This is an implicitly public open source repo**. Assume that anything committed and pushed to the github remote of the repo is public knowledge. 

Do not check in any sensitive api keys, tokens etc.

If this happens by accident, such "leaks" are hard to remove again fully from git due to its distributed nature, so secrets added to the git repo are considered compromised and have to immediately be updated/rotated in the system they access/belong to.

## We upgrade our dependencies often

Due to current landscape of LLM tooling, risks like supply chain attacks etc is much higher than it was before.
Therefore, our dependencies (python modules and npm packages that we depend on) 
need to be kept up to date frequently/continously.

## "Holding off" sharing some algorithms with published code?

If you have any algorithms or other sensitive work that should not land in the public repo right away 
(pending a paper being published or something like that),
we suggest you clone the public repo, then create your own feature branch that you work in (and keep rebased off the main repo regularly).

## DCO: signing off your commits

The Linux Foundation Energy hosts our project and requires the developers to sign off commits in all their work on the repo.
Signing off commits in this manner is a way to declare that your contribution complies with the points laid out in
https://developercertificate.org/

The repo has a DCO check on PRs. If it finds commits with missing signature in your PR, you can amend it on your branch 
like this:

`git rebase --signoff $(git merge-base HEAD main)`

Then force push, this should fix the issue.

## Write down the decisions that shape the system

Bigger architectural choices are recorded as short **Architecture Decision Records**
in [`doc/adr/`](adr/). Each one is a page or less: the context that forced the
choice, what we decided, what it costs us, and the alternatives we rejected.

Write one when: a choice is expensive to reverse, cuts across sub-teams, or is one
a newcomer would reasonably ask "why is it like this?". Small everyday
choices inside your own team's code do not need one.

An ADR is history, not documentation: we do not rewrite old ones, we write a new
one that supersedes them.

## Only complicate the rig when you have to :)

The project will do some computation intensive operations, and we may well have to split it into multiple processes/services to make it work.

But we try to start as simple as we can, and do more elaborate rigging only when/where actually needed, supported by performance numbers and experiments.

When you see that we need to add new infra/services/, keep the rest of the project/team in the loop 
(one possible way of doing this could be a PR with an ADR explaining the change - see above)
