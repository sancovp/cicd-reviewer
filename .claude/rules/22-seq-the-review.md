# 22-seq — THE REVIEW: a pull request's tip given a verdict — BLOCKING only for the change's own defect, every other finding OWED, a new tip read for what changed — then read by the queue, the sweep, the late review and the PR watch

<docsys kind="dev-flow" role="instance"/>

TRIGGER:[the reviewer's prompt, skill or rule changes (`ci_agent._classify` · `_review_prompt` · `_late_review_prompt`,
the `review-pr-diff` skill, the `review-discipline` rule) · the shape of a review's body changes (a finding line, the
verdict line) · `last_reviewed` · `prior_tip` · `blocked_findings` change · a reader of a review changes
(`sweep.verdict_of` and `last_verdict`, `merge_queue`'s freshness and `dispatch_review`, `outage.late_review` and
`close_late`, `pr_watch.snap_of` and `needs_action`) · a way a review gets dispatched is added or changed · the checkout
the reviewer runs in changes (`.github/workflows/review.yml`)] · a PROCEDURE flow: every stage runs every time · its
design is `../../DESIGN.md` §2 · §4 · §11

## RETRIEVE (in this order; whole)

| what | where |
|---|---|
| the design | `../../DESIGN.md` — ITS VERSIONS, §2 (the PR watch), §4 (the tiers), §5 (the queue), §11 (A REVIEW CONVERGES) |
| the board | `cicd_reviewer_states.md` (this folder) — THE FLOW's review and PR-watch rows, THE VERSIONS |
| the prompt and which tip a review reads on from | `../../ci_agent.py` whole: the marks, `_classify`, `_review_prompt`, `_late_review_prompt`, `_verdict`, `last_reviewed`, `blocked_findings`, `_agrees`, `verdict_posted`, `prior_tip`, `main` |
| the reviewer's identity | `../../cicd_aios/CLAUDE.md` · `../../cicd_aios/.claude/skills/review-pr-diff/SKILL.md` · `../../cicd_aios/.claude/rules/review-discipline.md` |
| the run's checkout and its hand-off | `../../.github/workflows/review.yml` whole: the payload and `BASE_REF`, the checkout at the head with `fetch-depth: 0`, the model probe, the run and its retry, the late review's close, the hand-off to the queue |
| who reads a review's body | `../../sweep.py` (`verdict_of`, `last_verdict`) · `../../merge_queue.py` (`fresh`, `changed_since`, `dispatch_review`, `run`'s re-reviews at the same tip) · `../../outage.py` (`late_review`, `close_late`) · `../../pr_watch.py` (`snap_of`, `needs_action`, `line`, `watch`) |
| the session's side | the rule `top-level-session-worktree` THE GIT LOOP points 2 and 5 |
| the tests | `../../tests/test_ci_agent.py` · `test_pr_watch.py` · `test_merge_queue.py` · `test_sweep.py` · `test_outage.py` |

## COHERENCE SET (what else changes because the review changed)

- the prompt, the `review-pr-diff` skill, the `review-discipline` rule, `cicd_aios/CLAUDE.md` and `DESIGN.md` §2 · §4 ·
  §11 say one thing: the two classes, the finding lines (`- BLOCKING:` · `- OWED (<project>):` · `- FIXED:`), the verdict
  line, the incremental diff command, which tip is prior
- every reader of the verdict reads it the same way (`ci_agent._verdict`, `_agrees`, `sweep.verdict_of`): a CLEAN verdict
  under a standing BLOCKING line is BLOCKING
- every copy of a finding mark carries the same text (`ci_agent.BLOCKING_MARK` · `OWED_MARK` · `FIXED_MARK`,
  `sweep.BLOCKING_MARK` · `OWED_MARK`, `pr_watch.OWED_MARK`)
- every way a review is dispatched is read against `last_reviewed`: a ready or pushed tip, the sweep's dispatch, the
  queue's re-review at the same tip, the retry of a run without its result, the late review
- the checkout `review.yml` makes holds `origin/<base>` and the head's whole history, which `prior_tip`'s merge bases need
- the PR watch's lines and the session's side say the same about OWED, MERGED and `--expect-head`
- the board's rows and THE VERSIONS, `CHANGELOG.md`, and `21-architecture-diagrams.md` when a box or an arrow changes

## THE CHANGE (what the review does, in order)

1. A review starts from what the pull request is for: its title, its description and the board of the project it changes.
2. It takes the diff: the whole pull request against the default branch, or — when `prior_tip` names a reviewed tip that
   is an ancestor of the head with the same merge base with `origin/<base>` — `git diff <tip> HEAD`, which then holds the
   pull request's own change and nothing else, together with the BLOCKING lines of that tip's review. A tip that already
   carries a verdict (UNREVIEWED included), a pull request with no usable reviewed tip, one that merged the default
   branch in since, and one whose head cannot be read are read whole.
3. Every finding is one line: `- BLOCKING:` when the pull request's own change adds it or makes it worse in what the pull
   request is for, `- OWED (<project folder>):` for every other, `- FIXED:` on a new tip for one blocked on before. The
   last line is `VERDICT: BLOCKING` when a BLOCKING line stands, else `VERDICT: CLEAN`.
4. The run's result is checked on GitHub: a review on the exact tip, posted since the run began, its lines agreeing with
   its verdict; anything else is no result, and the run tries once more.
5. The queue merges a fresh CLEAN verdict; the sweep reads the verdict; the late review posts the same lines as a comment
   on a merged pull request, and `close_late` opens Fix owed (BLOCKING) or Owed findings (OWED alone) holding them.
6. The PR watch exits BLOCKING on a BLOCKING tip, names the tip's OWED count on every line, and on MERGED says to record
   each OWED finding as a row on the board of the project it names, as work on the default branch. With `--expect-head`
   it judges nothing until GitHub shows that tip, exits PUSHED past it and TIP-UNSEEN after `EXPECT_WAIT_POLLS` polls.

## THE PROOF (per store, before and after)

| store | measurement | passes when |
|---|---|---|
| the review body on GitHub | after a publish, a review of a real pull request, then of a pushed fix: `gh api repos/<r>/pulls/<n>/reviews --jq '.[] \| .commit_id, .body'` | every finding is one marked line, the last line a verdict, a BLOCKING line standing only under `VERDICT: BLOCKING`; the second review reads only the fix and says FIXED or BLOCKING for each line the first blocked on |
| the prompt | `_review_prompt(..., prior)` printed for a first tip and for a later one | the first names no tip; the later names the tip, `git diff <tip> HEAD` and only the BLOCKING lines |
| the prior tip | `tests/test_ci_agent.py` over every way a review is dispatched | a later tip reads on from the newest usable reviewed tip; the same tip, UNREVIEWED, a rewritten history, a default-branch merge since and an unreadable head read whole |
| the readers of the verdict | `tests/test_sweep.py` · `test_merge_queue.py` · `test_outage.py` on bodies carrying finding lines | each reads the verdict the lines agree with |
| the PR watch | `tests/test_pr_watch.py` | OWED named on every line and recorded after MERGED, never an exit; the expected tip waited for, a tip past it PUSHED, one never seen TIP-UNSEEN |
| the session's record | the board an OWED line names, after the session acts on MERGED | a row per finding, in the board's own shape — never a note |
| every suite | the five suites, run bare and read | every case passes; each guard removed fails its case |

NOT:[let a finding block a pull request its own change did not add or make worse · review a new tip whole when a usable
reviewed ancestor exists and no one sent the tip back · read on from a tip when the default branch was merged in since ·
treat a tip the queue sent back as a new tip · read a tip with no readable head as one with a prior · count UNREVIEWED as
a review · let a verdict line disagree with the finding lines above it · put a finding anywhere but its own line · push a
row into a pull request the queue is merging · let a watch wait unbounded on a tip that may never arrive · drop the
findings of a late review · state in a document what the code does not do]
