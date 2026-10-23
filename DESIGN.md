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
answer, a pull request merges on its automatic checks and is reviewed after it merges (§2), so one model provider running
out never stops every session's work from reaching the default branch. No human does git, and no session merges. Git's API decides
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
        │         automatic check passed and labels it `review-owed` ──▶ the sweep sends it to the reviewer, merged, once the
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
pull request, is not one), or has its tip moved; and it
checks before it waits, so a pull request already in one of those states exits at once. A CLEAN verdict and a
mergeable state of UNKNOWN are not actions (the queue moves a CLEAN pull request; UNKNOWN is GitHub computing). It
never runs past `--max-hours` (default 4): it exits TIMEOUT saying where the pull request stands. Exit codes: 0 done ·
2 act · 3 timeout · 4 merged at another tip · 5 gh down.

| state | what it means | who moves it |
|---|---|---|
| DRAFT | parked, or still being worked on | a session marks it ready |
| READY | asking for a review | the reviewer |
| BLOCKING | a real defect found | the session that owns the work: fix, push |
| CLEAN | reviewed and fine on this exact tip | the merge queue |
| UNREVIEWED | the model did not answer at this tip; merged once its automatic checks pass, then labelled `review-owed` | the merge queue; after the merge, the sweep and the late review |
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
| a push to the default branch | the canonical home's `publish-on-main.yml` | publishing (path-gated) — not the CI | no |

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
branch, not a draft, not the standing branch, its verdict on its exact tip is CLEAN — or UNREVIEWED with every automatic
check passed (none failed, none still running; `checks_state`) — GitHub calls it mergeable, and it is not held at this tip. It is **fresh** when no commit has landed on the default branch since that verdict touching any of
its files (more than 100 commits since ⇒ not fresh). Ready-and-fresh PRs are grouped by shared files: a group of one
merges; a larger group goes to the coordinator, the first in its order merges, the rest are reviewed again against the
new main, each held one gets one comment; a group holding an UNREVIEWED PR skips the coordinator (it is the model, which
was down) and goes oldest first. A PR merged UNREVIEWED is labelled `review-owed`. A CONFLICT gets one comment. Every merge is a squash at the reviewed tip
(`--match-head-commit`), the branch deleted. Never a force push.

## 6. The sweep (`sweep.py` · `.github/workflows/sweep.yml`)

Daily over every source repository the owner has (not forks, not archived), every branch except the default and the
standing branch: its tip already on the default branch (GraphQL's comparison — never the REST diff, which fails on large
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
| `host-aios-dev` · `aisaac` | committed straight to the default branch, no PR (their own rules) |
| every other source repo | PRs, reviewed and merged only through the daily sweep — a day per round (ASPIRATIONAL: the one-step trigger of §3 in each active repo) |
| publish targets (`cave`, `chaincompiler`, `carton-mcp` …) | never merged into: their source is the canonical home |

The standing branch `om-is-the-base` (the mind_of_god machine's own line of work) is never reviewed, queued, swept or
merged; its PR #165 is a draft.

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
edits the issue). **The reviewer's MiniMax plan is the reviewer's alone:** no box, seat, agent or test runs on it, so
nothing else can spend it; anything else that needs MiniMax runs on a plan of its own. The test business's JobWorld box and
the HealthWorld box ran on it; both are off until each has a plan of its own (the board's OPEN). This directory is authored in the canonical home at `automation/cicd-reviewer/` and mirrored here by
`scalable-publishing` on every push to the default branch that touches it — never edited here.

## 11. Laws

- Only the merge queue merges; nothing merges without a verdict on the exact tip — CLEAN, or UNREVIEWED with every
  automatic check passed — and a verdict counts only while fresh.
- Merges never wait on the model: a PR merged UNREVIEWED is reviewed after it merges, and a defect found then opens a fix.
- The reviewer's MiniMax plan is the reviewer's alone.
- Nothing fires on a draft or on the standing branch.
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
| every push to a PR re-reviewed half-finished work | reviews only for ready PRs; drafts fire nothing |
| a test JobWorld box's heartbeat, left on, spent the whole MiniMax plan the reviewer runs on, and no pull request from any session could merge for days | the plan is the reviewer's alone (§10); the model's check marks a tip UNREVIEWED and the queue merges it on its automatic checks, the review after the merge (§2) |
| an AI opening PRs on branch creation raced the sessions' own | removed; sessions open their own, the sweep catches the rest |

## 13. Built, and owed

BUILT and proven live: the verdict line · the merge queue (#1486, #1487, #1488, #1490, #1491 merged with nobody
touching them) · the coordinator (asked about #1476 and #1477, it held #1477 with the exact reason) · the sweep (389 merged
branches deleted, 23 PRs opened) · the tracking issue · draft parking. BUILT, tests green, to prove live while the model
is down: the model's check and the UNREVIEWED mark · the queue merging UNREVIEWED on its checks and labelling it · the late
review and its "Fix owed" issue. ASPIRATIONAL: the review trigger in every active
repo (§8) · the harvest moved here, drafting its rule PRs (§9) · a cost meter (reviews and model spend per day).

## 14. How to change it

Edit here, in the canonical home, never in the public repo. A change opens a ready PR like any other — the reviewer
reviews its own code and the queue merges it — except a change to the merge path itself, which cannot review itself
before it is published: merge it after a CLEAN verdict by hand, then prove the published version live. Run before every
push: `python3 tests/test_merge_queue.py` · `python3 tests/test_sweep.py` · `python3 tests/test_ci_agent.py` ·
`python3 tests/test_pr_watch.py` · `python3 tests/test_outage.py`, all green;
a guard added gets a test that fails with the guard removed. After a publish, prove the changed path live on a real PR.
