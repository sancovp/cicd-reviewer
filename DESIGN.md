# cicd-reviewer — DESIGN

## 0. This document

The one design of the CI: how work gets from a session's branch onto the default branch, every trigger, every
workflow, both AI tiers, the merge queue, the sweep, what each costs, what is built and what is owed. It covers both
halves: the reviewer (this directory, published to the public `sancovp/cicd-reviewer`, whose free Actions minutes run
it) and the one trigger in the canonical home (`.github/workflows/cicd-review-on-pr.yml`). Work state: the board
`.claude/rules/cicd_reviewer_states.md` (its `## OPEN` table is what waits on *USER*). The stack:
`.claude/rules/21-architecture-diagrams.md`. History: `CHANGELOG.md` beside this file (publishing never copies it).
The session's side of the flow is also a rule every session carries: `top-level-session-worktree` (THE GIT LOOP).

## 1. What it is, and the one law

**WORK IS DONE ONLY WHEN IT IS ON THE DEFAULT BRANCH, AND ONLY THE MERGE QUEUE MERGES.** Sessions write the work and
hand it off as a pull request; the CI reviews it, merges it one at a time, and sweeps every repository so no branch is
left holding work that is not on its default branch. **MERGES NEVER WAIT ON THE MODEL:** when the reviewer's model does not
answer, a pull request merges on the checks its repository's own workflows run and is reviewed after it merges (§2), so one model provider running
out never stops every session's work from reaching the default branch. **MERGES NEVER WAIT ON ACTIONS EITHER:** when GitHub
Actions starts no job at all — the account's billing refused — nothing of the CI runs, so the session is the CI: it takes
every ready pull request through the queue's steps by hand (§5 THE QUEUE BY HAND), and each one it merges is labelled
`review-owed` and read by the reviewer once jobs start again. No human does git, and while the CI runs no session merges. Git's API decides
everything git's API can decide; the model is called only for what needs judgment — reading a change (the reviewer),
and reading several changes together (the coordinator).

## 2. The flow — a pull request's life

```
 session works on a branch, pushes as it goes ──────────────────────────────── nothing fires
        │
        ▼  the work is done: branch brought up to date with the default branch, no conflict
 PR opened READY by the session ───────────────────────────────────────────── one review
        │                     (a DRAFT is parked or in progress: nothing fires, ever)
        ▼
 first: is the model answering? (one one-token question, three tries a minute apart — outage.py)
        ├─ no ──▶ VERDICT: UNREVIEWED on the tip, posted without the model ──▶ the merge queue, which merges it once every
        │         own-workflow check passed and labels it `review-owed` ──▶ the sweep sends it to the reviewer, merged, once the
        │         model answers ──▶ its late review: CLEAN takes the label off · BLOCKING opens a "Fix owed" issue
        ▼ yes
 REVIEWED — the review's last line is the verdict, on the PR's exact tip
        ├─ VERDICT: BLOCKING ──▶ the session fixes and pushes ──▶ one review of the new tip
        └─ VERDICT: CLEAN ──▶ the merge queue (one run at a time per repo)
                 ├─ not fresh (main changed its files since the verdict) ──▶ reviewed again
                 ├─ conflicts with main ──▶ one comment; the session merges main in, pushes ──▶ reviewed again
                 ├─ shares files with another ready PR ──▶ the coordinator orders them / holds one
                 └─ ready, fresh, alone or first in order ──▶ MERGED (squash at the reviewed tip, branch deleted)
 the session waits while it runs — through the PR watch (`pr_watch.py`), never a loop of its own — and confirms MERGED;
 if it ends first, the work is listed in UNMERGED WORK and the next session in that repository clears it before anything else
```

**The PR watch** (`python3 automation/cicd-reviewer/pr_watch.py <n> --expect-head <your last pushed sha>`, run in the
background) is how a session waits. The harness wakes a session only when a background task exits, so the watch exits
— once, with one line naming what to do — when the pull request is MERGED (at the expected tip, or exit 4: carry the
rest in a new PR) or CLOSED, CONFLICTING, BLOCKING on its tip, gets a new comment (a deploy preview's status comment, posted on every
pull request, is not one), or has its tip moved, or when the review trigger failed at its tip and no
verdict is on the tip (REVIEW-FAILED: no run of the trigger at the tip succeeded or is still running, and the last one
failed, timed out, failed to start or waits for approval — never one cancelled, which is the trigger's concurrency group
superseding it; no review is coming, so re-run it when GitHub failed to start it, or, when its jobs were refused for the
account's billing, be the CI by §5); it reads those runs beside the reviews because a failed run posts no verdict, so a
watch reading the reviews alone waited on it until its cap. It checks before it waits, so a pull request
already in one of those states exits at once. A CLEAN verdict and a
mergeable state of UNKNOWN are not actions (the queue moves a CLEAN pull request; UNKNOWN is GitHub computing). It
never runs past `--max-hours` (default 4): it exits TIMEOUT saying where the pull request stands. Exit codes: 0 done ·
2 act · 3 timeout · 4 merged at another tip · 5 gh down.

**While GitHub Actions starts no job** (a review job that fails in seconds with no steps, its annotation naming the
account's payments or spending limit — the PR watch exits REVIEW-FAILED on it), nothing above moves a pull request: the
session hands its own off ready as always, then lands it — and every other ready pull request the stop holds up — by §5's
queue by hand.

| state | what it means | who moves it |
|---|---|---|
| DRAFT | parked, or still being worked on | a session marks it ready |
| READY | asking for a review | the reviewer |
| BLOCKING | a real defect found | the session that owns the work: fix, push |
| CLEAN | reviewed and fine on this exact tip | the merge queue |
| UNREVIEWED | the model did not answer at this tip; merged once its own workflows' checks pass, then labelled `review-owed` | the merge queue; after the merge, the sweep and the late review |
| STALE | CLEAN, but main has since changed its files | the queue sends it for review again |
| CONFLICT | GitHub cannot merge it | the session: merge the default branch in, both sides kept, push |
| HELD | the coordinator found it contradicts or breaks with another | the session, with the coordinator's reason |
| MERGED | on the default branch — done | — |

## 3. The triggers — what calls the CI, and what it costs

| event | workflow (repo) | what runs | model? |
|---|---|---|---|
| a PR opened ready, marked ready, reopened, or pushed to while ready — never a draft, never `om-is-the-base` | `cicd-review-on-pr.yml` (the canonical home — private, billed, ~1 min: the SkillTree structure gate, then a dispatch) → `review.yml` (here) | one review | yes, one review |
| a review finishes | `review.yml` hands off → `merge-queue.yml` (here) | the merge queue | only if PRs overlap (the coordinator) |
| daily, 07:17 UTC | `sweep.yml` (here) | the sweep over every source repo, and the late reviews owed | only in the reviews it dispatches, ≤10 a run, 3 min apart |
| the model refuses (429 · 5xx · no answer · 401/403), three tries a minute apart | `review.yml`'s first step (`outage.py probe`) | `VERDICT: UNREVIEWED` posted on the tip, the queue handed it | no — one one-token question |
| the default branch moves | the absorber's job file on the OM daemon's calendar, every fifteen minutes, on our own machine (`scalable-publishing/DESIGN.md` §1) — not a GitHub workflow | publishing — not the CI | no |
| a push to the default branch touching `application/lamai-saas`'s code — not only its documents (its `.md` files, `.claude/`, `records/`, `docs/`) | the canonical home's `deploy-lamai-on-main.yml` | LAMAI's deploy (path-gated; `application/lamai-saas` DESIGN §4) — not the CI | no |

A commit does not call the CI. A push to a branch with no ready PR does not call it. Nothing fires when a branch is
created: a session opens its own PR, and the sweep opens one for a branch left without one.

## 4. The two AI tiers

| tier | reads | decides | skill |
|---|---|---|---|
| **THE REVIEWER** (`MODE=review`) | one PR's diff | its verdict: the review's last line, `VERDICT: CLEAN` or `VERDICT: BLOCKING`, posted with `--comment` (GitHub refuses approve / request-changes from the account that owns the PR) | `cicd_aios/.claude/skills/review-pr-diff` |
| **THE LATE REVIEW** (`MODE=review-merged`) | one PR merged `UNREVIEWED`, its diff | its verdict, as a comment on the merged PR ending `VERDICT: CLEAN` or `VERDICT: BLOCKING`; BLOCKING opens a "Fix owed" issue (`outage.py close-late`) | `cicd_aios/.claude/skills/review-pr-diff` |
| **THE COORDINATOR** (`MODE=coordinate`) | every ready, fresh PR that shares files with another | their merge order, and which to HOLD (contradicts, undoes or breaks with another), each with a one-sentence reason — written to `/out/decision.json` | `cicd_aios/.claude/skills/coordinate-merges` |

Both tiers run in heaven's AGENT MODE: one conversation, up to 100 rounds (`CICD_ITERATIONS`) of at most 15 tool calls
each (`CICD_ROUND_STEPS`), ending when the agent declares its goal accomplished — so a large PR is read in as many rounds
as it needs; there is no step limit on the run. A run succeeds only when its result exists in the world — a review
ending in a verdict line on the PR's tip, posted during the run (`ci_agent.verdict_posted`); the coordinator's
`/out/decision.json` — never because of what the agent said; a run without its result gets one more attempt. A review never merges. The coordinator never merges,
comments or reviews; the queue acts on its file, and with no decision falls back to oldest first, nothing held.

## 5. The merge queue (`merge_queue.py` · `.github/workflows/merge-queue.yml`)

One run at a time per repository (the workflow's concurrency group). A PR is **ready** when it is open into the default
branch, not a draft, not from the standing branch or from the branch the repository's GitHub Pages site is built from
(every merge deletes its branch, and that branch is the live site), its verdict on its exact tip is CLEAN — or UNREVIEWED with every check its
repository's own workflows ran passed (none failed, none still running; `checks_state`) — GitHub calls it mergeable, and it is not held at this tip. It is **fresh** when no commit has landed on the default branch since that verdict touching any of
its files (more than 100 commits since ⇒ not fresh). Ready-and-fresh PRs are grouped by shared files: a group of one
merges; a larger group goes to the coordinator, the first in its order merges, the rest are reviewed again against the
new main, each held one gets one comment; a group holding an UNREVIEWED PR skips the coordinator (it is the model, which
was down) and goes oldest first. A PR merged UNREVIEWED is labelled `review-owed`. A CONFLICT gets one comment. Every merge is a squash at the reviewed tip
(`--match-head-commit`), the branch deleted. Never a force push.

**The checks it counts** are those the repository's own workflows run — GitHub gives each a workflow name. An outside
app's check (a hosting provider's preview build, a commit status) carries none and is not counted: Cloudflare's preview
build of the business site runs on every pull request in the canonical home, whatever it touches, and fails on every one.
In the canonical home the own checks are the review trigger's SkillTree structure gate (§3) and, for the inner app's
source, `validate-inner-app.yml`; no workflow runs a project's tests, so a pull request merged UNREVIEWED is read only by
its late review.

**THE QUEUE BY HAND.** While GitHub Actions starts no job, the session does the queue's work itself, by the same tests
and in the same order, in every repository the CI covers (§8). A pull request is ready when it is open into the default
branch, not a draft, not from the standing branch or the Pages source branch, and GitHub calls it mergeable; the checks
that never started are not counted. The session reads first every review already on its exact tip: a verdict the reviewer gave there stands, and a
BLOCKING one is answered in writing — fixed on a new tip, or shown wrong — before anything else. Then it reads the diff
whole and posts its verdict on that tip as the reviewer would, as a review comment (`gh pr review <n> --comment`, the
channel the sweep and the queue read; an issue comment is invisible to them) — `VERDICT: CLEAN` or `VERDICT: BLOCKING`,
each with its reason. A CLEAN one that is fresh merges as a squash at that tip
(`gh pr merge <n> --squash --match-head-commit <sha>`, alone in its call), its branch then deleted in a call of its own
(`gh api -X DELETE repos/<owner>/<repo>/git/refs/heads/<branch>`; the harness refuses `--delete-branch` on the merge),
and is labelled `review-owed`, so the reviewer reads it once jobs start again; ready pull requests sharing files go
oldest first, each next one read again against the new default branch. A BLOCKING one gets its reason, and a CONFLICT one
comment; the session that owns it fixes it or merges the default branch in, and when that session has ended, the
session holding the CI does. The session's own pull request goes the same way, its verdict and its label included; one
the harness will not let the session that opened it merge is merged by the next session that holds the CI. No merge, no
held pull request and nothing about the stop is ever put to the owner. A
pull request that §8 never merges is not merged by hand either: a publish target's or a frozen copy's gets the comment
that sends its work to its source in the canonical home, and one whose repository keeps its branch unmerged by design —
a Pages source branch among them — is parked as a draft with its reason.

## 6. The sweep (`sweep.py` · `.github/workflows/sweep.yml`)

Daily over every source repository the owner has (not forks, not archived), every branch except the default, the
standing branch and the branch the repository's GitHub Pages site is built from (`pages_branch`: `repos/…/pages` is
asked only where the repository's own `has_pages` says it has a site, so a token that cannot read Pages pauses only
those repositories; a 404 means no site, and a repository whose site cannot be read is skipped that run, never swept
blind): its tip already on the default branch (GraphQL's comparison — never the REST diff, which fails on large
ones) ⇒ deleted · a draft PR ⇒ PARKED · a ready PR with a CLEAN or UNREVIEWED verdict ⇒ its repo handed to the merge queue ·
no verdict ⇒ a review dispatched · no PR ⇒ one opened, ready · a CONFLICT or BLOCKING ⇒ STUCK · a branch of a PUBLISH TARGET (a repo
the publishing pipeline overwrites, read from `scalable-publishing/publish-manifest.json`) ⇒ STUCK, to be ported into its
source in the canonical home, never merged there. Then every merged PR labelled `review-owed`, in any repository the
owner has, is sent to the reviewer, merged (its default branch checked out), within the same review budget: its late
review runs once the model answers, and the label stays until a verdict lands.

## 7. The tracking issue — `UNMERGED WORK`

One issue on the canonical home, rewritten by every sweep: **STUCK** (work the CI cannot move — conflicts,
BLOCKING verdicts, publish targets; each with why), **PARKED** (drafts), and **REVIEW OWED** (merged while the model was
down, their late reviews pending). A late review that finds a defect opens its own "Fix owed" issue in its repository. A session starting work in a repository reads
that repository's STUCK rows and clears them before anything else.

## 8. Repositories and their policy

| repository | how work reaches its default branch |
|---|---|
| the canonical home (`sanctuary-revolution-alpha`) | the full flow (§2) — the only repo that triggers reviews on its own PRs |
| `host-aios-dev` · `aisaac` | committed straight to the default branch, no PR (their own rules); a PR the sweep opened for a branch there is parked as a draft, its branch's work reaching the default branch only by that repository's own loop |
| every other source repo | PRs, reviewed and merged only through the daily sweep — a day per round (ASPIRATIONAL: the one-step trigger of §3 in each active repo) |
| publish targets (`cave`, `chaincompiler`, `carton-mcp` …) | never merged into: their source is the canonical home |
| frozen copies — a standalone repository whose project was folded into the canonical home (`onionmorph`, `agent-rts`, `twi-jobworld`, `gas_bootstrap_depth_system`, `map` — MAP at `base/crystal-ball-alpha/MAP/map`) or kept for reference only (`matrix`) | never merged into: a branch's work missing from the canonical home is ported there (union, zero deletes), by the project's own lane |

The standing branch `om-is-the-base` (the mind_of_god machine's own line of work) is never reviewed, queued, swept or
merged; its PR #165 is a draft. A repository's GitHub Pages source branch is the live site, so it is never queued, swept,
merged or deleted either; of the owner's 15 Pages sites one is built from a branch other than its default —
`director-cinematic-site`'s `gh-pages` — and the pull request the sweep once opened for it is parked as a draft.

## 9. Self-maintenance — the rule harvest (OFF)

`cicd-rule-harvest.yml` (the canonical home) ran the reviewer in `MODE=harvest` weekly: read its own past reviews, turn
a recurring finding into a candidate rule, open a PR. Every run since at least 2026-09-21 failed — the agent spent its 40
tool calls and never finished — on billed minutes, so it is manual only. Owed before it runs again: it moves to this repo
(free minutes) and opens its rule PRs as DRAFTS, because the queue merges any ready PR with a CLEAN verdict and the
reviewer must not approve a rule it wrote; who marks a rule PR ready is OPEN (the board).

## 10. Where it runs and what it holds

The reviewer's image `ghcr.io/sancovp/cicd-reviewer` (built by `build-image.yml` when `ci_agent.py`, `cicd_aios/`,
`entrypoint.sh` or the `Dockerfile` change) runs on this public repo's runners with two secrets: `MINIMAX_API_KEY` (the
model) and `PUBLISH_TOKEN` (reads the private canonical home, posts reviews and comments, merges, deletes branches,
edits the issue). **Our one MiniMax key runs the reviewer, on a subscription with a cap, so nothing can spend past it.**
No box holds it: the one other use is the test business's JobWorld box, during a proof that needs its agent to answer,
its loop off, the key unset when the proof ends — so a proof is kept to its minutes, since every minute it runs is the
reviewer's plan too. GHL's reviewers never reach that box: the add-on's review videos are filmed on it during such a proof (`application/jobworld`
DESIGN §9 THE LAUNCH GATE).
The HealthWorld box's model is the board's OPEN, the box off until then. This directory is authored in the canonical home at `automation/cicd-reviewer/` and mirrored here by
`scalable-publishing` on every push to the default branch that touches it — never edited here.

## 11. Laws

- Only the merge queue merges — or, while GitHub Actions starts no job, the session doing its steps by hand (§5);
  nothing merges without a verdict on the exact tip — CLEAN, or UNREVIEWED with every check of the repository's own
  workflows passed — and a verdict counts only while fresh.
- Merges never wait on Actions: while it starts no job, every pull request the session merges is `review-owed`.
- Merges never wait on the model: a PR merged UNREVIEWED is reviewed after it merges, and a defect found then opens a fix.
- Our one MiniMax key, on a capped subscription, runs the reviewer; no box holds it but the test business's during a proof, its loop off, unset after.
- Nothing fires on a draft or on the standing branch.
- A GitHub Pages source branch is the live site: never merged, never deleted.
- The model never does what git's API can do.
- No fork-reachable trigger on any workflow here: this public repo holds a token that reads the private canonical home.
- Never a force push, anywhere.

## 12. Failures seen, and the guard each now has

| failure | guard |
|---|---|
| every review was a comment nothing read, so nothing merged (415 branches piled up) | the verdict line; the queue |
| a PR merged before its review ran, so the review failed on a deleted branch | sessions never merge; the review skips a closed or draft PR |
| 14 reviews at once, all refused by the model (429) | reviews dispatched 3 min apart, ≤10 a sweep |
| the agent said "Done." / a "done" inside an error, and the run's result was misread | the run checks GitHub for the posted verdict |
| on a large PR the reviewer spent its 40 tool calls in ONE round and stopped before posting (#1500) — a plain prompt runs heaven's single round | heaven's agent mode: up to 100 rounds of 15 calls, one conversation, until the goal is accomplished |
| independent CLEAN verdicts wrong together (#1465 / #1470) | freshness; one merge at a time; the coordinator |
| a merge into a publish target would be overwritten by the next publish | the sweep lists those branches for porting |
| REST compare answered 500 on large diffs | GraphQL's comparison |
| the freshness check read `gh api --jq '.[].sha'` through the JSON-per-line reader; `--jq` prints a string raw, so the first sha after any commit on main crashed the run — nine queue runs failed in a row and nothing merged for hours while every verdict was CLEAN | `gh_strings` reads `--jq` string output raw; the tests' fake GitHub answers those calls raw, as gh does, so the crash fails a test |
| sessions waited on hand-written loops: one baselined CONFLICTING and looped four hours (#1561), one started after its merge and ran all night (#1599), one had to be patched to keep going past CLEAN (#1566) — each a deploy or a fix hours late | the PR watch (`pr_watch.py`): checks before it waits, exits on every state the session must act on, never past its cap; a test per failure |
| the first attempt of the review trigger's run at a pull request's tip failed before any job started (#2435), so no review came, and the PR watch, reading only the reviews, waited toward its cap — as every watch did while Actions refused jobs for billing | the PR watch reads every trigger run at the tip and exits REVIEW-FAILED when none succeeded or still runs and the last failed (a cancelled run is the trigger superseding itself, never a failure) while no verdict is on the tip; its tests fail with either half of the guard removed |
| every push to a PR re-reviewed half-finished work | reviews only for ready PRs; drafts fire nothing |
| a test JobWorld box's heartbeat, left on, spent the whole MiniMax plan the reviewer runs on, and no pull request from any session could merge for days | no box holds the key between proofs, and a proof runs with the box's loop off (§10); the model's check marks a tip UNREVIEWED and the queue merges it on its own workflows' checks, the review after the merge (§2) |
| the first queue built to merge UNREVIEWED pull requests counted every check, and Cloudflare's preview build of the business site fails on every pull request in the canonical home, so it would have merged none | the queue counts only the checks the repository's own workflows run (§5); a test pins Cloudflare's own shape, and fails with the guard removed |
| an AI opening PRs on branch creation raced the sessions' own | removed; sessions open their own, the sweep catches the rest |
| GitHub Actions started no job — the account's billing refused — so the trigger, the reviewer, the queue and the sweep all stopped, and 23 ready pull requests across 12 repositories waited with no verdict | the queue by hand (§5): while jobs do not start the session is the CI, and everything it merges is `review-owed` |
| working the queue by hand, the session read `cyberneticircus` #4's diff but not the review already on its tip — the reviewer's BLOCKING, a stored XSS (a page title breaking out of a `data-title` attribute) — and merged it CLEAN; the hand verdicts also went out as issue comments, which the sweep and the queue never read | the queue by hand reads every review on the tip first and answers a standing BLOCKING in writing before judging; its verdict is a review comment (§5); the XSS fix is `cyberneticircus` #5 |
| the sweep opened a pull request from `director-cinematic-site`'s `gh-pages`, the branch its GitHub Pages site is built from, and every way of merging it hurt the site: the queue's squash deletes the branch, a merge commit puts its tip on the default branch where the sweep deletes it, and a squash alone leaves it ahead, reopened daily | the sweep and the queue read each repository's Pages source (`pages_branch`) and keep it as they keep the standing branch; a repository whose site cannot be read is skipped; a test of each fails with the guard removed |

## 13. Built, and owed

BUILT and proven live: the verdict line · the merge queue (#1486, #1487, #1488, #1490, #1491 merged with nobody
touching them) · the coordinator (asked about #1476 and #1477, it held #1477 with the exact reason) · the sweep (389 merged
branches deleted, 23 PRs opened) · the tracking issue · draft parking · the outage path up to the merge (with the model
down, every reviewed tip was marked UNREVIEWED and the queue merged video-aios#27, #1985, #1986, #1987 and #1996 on their
own workflows' checks, each labelled `review-owed`). BUILT, tests green, to prove once the model answers: the late review
and its "Fix owed" issue. ASPIRATIONAL: the review trigger in every active repo (§8) · the harvest moved here, drafting
its rule PRs (§9) · a cost meter (reviews and model spend per day) · a failed review shown failed on the pull request (the
canonical home's check is the trigger's dispatch, green whatever the review then does).

## 14. How to change it

Edit here, in the canonical home, never in the public repo. A change opens a ready PR like any other — the reviewer
reviews its own code and the queue merges it — except a change to the merge path itself, which cannot review itself
before it is published: merge it after a CLEAN verdict by hand, then prove the published version live. **While the model
is down, or GitHub Actions starts no job, the owner's word covers every merge until it returns:** the session that holds
the CI merges a merge-path change by hand, lands every pull request the stop holds up by §5's queue by hand (resolving
their conflicts too) and never raises a merge, a held pull request or the stop itself with the owner. Prove such a change against real pull requests' data and under the runner's own shell (`bash -e`)
before it merges, so that one merge carries the whole fix. Run before every push: `python3 tests/test_merge_queue.py` · `python3 tests/test_sweep.py` · `python3 tests/test_ci_agent.py` ·
`python3 tests/test_pr_watch.py` · `python3 tests/test_outage.py`, all green;
a guard added gets a test that fails with the guard removed. After a publish, prove the changed path live on a real PR.
