# cicd-reviewer — TASKS

TRIGGER:[work in this dir]

N tables, one per WORKFLOW TYPE (rule 28). Prose → [`../../DESIGN.md`](../../DESIGN.md). **§ OPEN = what waits on
*USER*; § THE FLOW = each piece of the CI and how far it has come.**

## OPEN

A question only *USER* can answer moves: **RAISED** (named) → **PUT** (put to *USER*) → **RULED** (answered) →
**CLEARED** (the work it unblocked has moved). `●` = reached.

| question for *USER* | where it is detailed | RAISED | PUT | RULED | CLEARED |
|---|---|:-:|:-:|:-:|:-:|
| who marks the rule harvest's draft pull requests ready — the reviewer must not approve a rule it wrote | [§9](../../DESIGN.md) | ● | | | |
| how fast other repos' pull requests should merge — daily through the sweep, or the review trigger installed in each active repo | [§8](../../DESIGN.md) | ● | | | |
| OM Daily Driver (#1476, parked as a draft) — keep, change or drop | [§8](../../DESIGN.md) | ● | ● | | |
| merges never wait on the model — ruled: when the reviewer's model is down, the queue merges on the automatic checks and the review runs after the merge; our one MiniMax key (a capped subscription) runs it and a test-box proof alone; until it answers, the session holding the CI lands every merge | [§2](../../DESIGN.md) · [§10](../../DESIGN.md) · [§14](../../DESIGN.md) | ● | ● | ● | ● |
| merges never wait on Actions — ruled: while GitHub Actions starts no job (the account's billing), the session handles every pull request by the queue's steps by hand, each merge `review-owed` | [§1](../../DESIGN.md) · [§5](../../DESIGN.md) · [§14](../../DESIGN.md) | ● | ● | ● | ● |
| which model the HealthWorld box runs on (off until then); the test business's box for a proof — ruled: our one MiniMax key (a capped subscription), for that proof alone, loop off, unset after (JobWorld §9) | [§10](../../DESIGN.md) | ● | ● | | |

## THE FLOW

A piece of the CI moves: **SCOPED** (designed) → **BUILT** (the code exists, tests green) → **PROVEN** (run live on a
real pull request) → **LIVE** (what every pull request goes through). `●` = reached.

| piece | where it is detailed | SCOPED | BUILT | PROVEN | LIVE |
|---|---|:-:|:-:|:-:|:-:|
| the verdict line — every review ends `VERDICT: CLEAN` or `VERDICT: BLOCKING` | [§4](../../DESIGN.md) | ● | ● | ● | ● |
| a review run checked on GitHub for its posted verdict, retried once | [§4](../../DESIGN.md) | ● | ● | ● | ● |
| the merge queue — one merge at a time per repo, verdicts counted only while fresh | [§5](../../DESIGN.md) | ● | ● | ● | ● |
| the coordinator — orders overlapping ready pull requests, holds contradictions | [§4](../../DESIGN.md) | ● | ● | ● | ● |
| the sweep — every repo daily: delete merged branches, open missing pull requests, dispatch reviews | [§6](../../DESIGN.md) | ● | ● | ● | ● |
| the `UNMERGED WORK` issue — STUCK and PARKED | [§7](../../DESIGN.md) | ● | ● | | |
| drafts fire nothing — reviews only for ready pull requests; queue and sweep skip drafts | [§2](../../DESIGN.md) · [§3](../../DESIGN.md) | ● | ● | | |
| no AI opener on branch creation — sessions open their own pull requests | [§3](../../DESIGN.md) | ● | ● | | |
| sessions never merge — the session rule hands off and waits | [§2](../../DESIGN.md) | ● | ● | | |
| the PR watch — a session waits through `pr_watch.py`, which exits on every state it must act on | [§2](../../DESIGN.md) | ● | ● | ● | |
| the PR watch reads the review trigger's runs at the tip — none succeeded or running, the last failed, no verdict on the tip: it exits REVIEW-FAILED | [§2](../../DESIGN.md) · [§12](../../DESIGN.md) | ● | ● | | |
| the PR watch reads a trigger run stalled in the queue — twenty minutes queued, no verdict on the tip: it exits REVIEW-STALLED naming the re-trigger | [§2](../../DESIGN.md) · [§12](../../DESIGN.md) | ● | ● | | |
| the review trigger in every active repo | [§8](../../DESIGN.md) | ● | | | |
| the rule harvest moved here, its rule pull requests drafts | [§9](../../DESIGN.md) | ● | | | |
| a cost meter — reviews and model spend per day | [§13](../../DESIGN.md) | ● | | | |
| merges never wait on the model — the model's check, the UNREVIEWED mark, the queue merging on its own workflows' checks and labelling `review-owed` | [§2](../../DESIGN.md) · [§5](../../DESIGN.md) | ● | ● | ● | |
| the queue by hand — while Actions starts no job, a session reads each ready pull request, posts its verdict and merges a clean, fresh one `review-owed` | [§5](../../DESIGN.md) | ● | ● | ● | |
| the Pages source guard — the sweep and the queue keep the branch a repository's GitHub Pages site is built from, as they keep the standing branch | [§6](../../DESIGN.md) · [§8](../../DESIGN.md) | ● | ● | | |
| the late review — a merged `review-owed` pull request reviewed once the model answers; BLOCKING opens a fix issue | [§4](../../DESIGN.md) · [§6](../../DESIGN.md) | ● | ● | | |
| one tracking issue and one fix issue however close together runs fall — the oldest open `UNMERGED WORK` kept, any other closed; a late review acting only when its removal of `review-owed` is the one GitHub accepts | [§6](../../DESIGN.md) · [§7](../../DESIGN.md) · [§12](../../DESIGN.md) | ● | ● | | |
| a failed review shown failed on the pull request — today the canonical home's check is the dispatch, green whatever the review does | [§13](../../DESIGN.md) | ● | | | |
