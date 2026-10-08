# cicd-reviewer — DESIGN

## 0. This document

The one design of the CI agent: what it is, its two tiers, the merge queue, and the sweep. The code it describes is
in this directory; the history of changes is `CHANGELOG.md` beside it. Authored in the monorepo at
`automation/cicd-reviewer/` and published to the public `sancovp/cicd-reviewer`, whose free Actions minutes run it.

## 1. What it is

**Work is done only when it is on the default branch.** The CI agent is what makes that true without a person: it
reviews every pull request, merges what is clean one at a time, and sweeps every repository the owner has so no
branch is left holding work that is not on its default branch. Git's API decides everything git's API can decide;
the model is called for what only judgment can do — reading a change.

## 2. The two tiers

| tier | what it reads | what it decides | where |
|---|---|---|---|
| **THE REVIEWER** (`MODE=review`) | one pull request's diff | its verdict — the review's last line, `VERDICT: CLEAN` or `VERDICT: BLOCKING` | `cicd_aios/.claude/skills/review-pr-diff` |
| **THE COORDINATOR** (`MODE=coordinate`) | every ready pull request that shares files with another | their merge order, and which to hold because it contradicts, undoes or breaks with another | `cicd_aios/.claude/skills/coordinate-merges` |

Reviews run in parallel, because they only read; they are dispatched spaced (`sweep.REVIEW_SPACING`), because the
model refuses a burst. A review never merges. The coordinator is called only when ready pull requests overlap — the
one place a set of independent CLEAN verdicts can be wrong together.

## 3. The merge queue (`merge_queue.py` · `.github/workflows/merge-queue.yml`)

One run at a time per repository (the workflow's concurrency group), dispatched after every review and by the sweep.
- **READY:** open into the default branch, the verdict on its EXACT tip CLEAN, GitHub calls it mergeable, not held at
  this tip.
- **FRESH:** nothing has landed on the default branch since that verdict touching the pull request's files; a stale
  verdict was given about a main that no longer exists, so the pull request is reviewed again and waits.
- **GROUPS:** ready-and-fresh pull requests joined by shared files. A group of one merges. A larger group goes to the
  coordinator; the first in its order merges, the rest are reviewed again against the new main, and each held one gets
  one comment with the reason (skipped until its tip changes). No decision from the coordinator ⇒ oldest first,
  nothing held: the queue never stalls.
- **A CONFLICT** gets one comment; the session that owns the work merges the default branch in, keeping both sides,
  and pushes.
- Every merge is a squash at the reviewed tip (`--match-head-commit`), the branch deleted. Never a force push.

## 4. The sweep (`sweep.py` · `.github/workflows/sweep.yml`)

Once a day over every source repository the owner has (not forks, not archived), every branch except the default and
the one standing branch (`om-is-the-base`): already on the default branch ⇒ deleted · an open pull request with a
CLEAN verdict ⇒ its repository handed to the merge queue · no verdict ⇒ a review dispatched · no pull request ⇒ one
opened · a branch of a PUBLISH TARGET (a repository the publishing pipeline overwrites) ⇒ never merged there, listed
for porting into its source in the canonical home. What it cannot move is rewritten every run into ONE issue,
`UNMERGED WORK`, on the canonical home. At most 10 reviews a run.

## 5. Laws

- No fork-reachable trigger on any workflow here: this public repository holds a token that reads the private monorepo
  (`review.yml`'s security note).
- The model never does what git's API can do (whether a pull request exists, whether a tip is on main, mergeability).
- A verdict counts only on the exact tip, and only while fresh.

## 6. Proof

`tests/test_merge_queue.py` (16: groups, freshness, the coordinator's decision and its fallback, holds, conflicts,
dry runs, run() against a fake GitHub — the freshness and grouping tests fail with those checks removed) ·
`tests/test_sweep.py` (14) · `tests/test_ci_agent.py` (9). Live: pull requests reviewed and merged by the agent with
nobody touching them; the sweep's first runs deleted 389 merged branches and opened 23 pull requests.
