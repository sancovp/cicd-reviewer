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
| merges never wait on the model — ruled: when the reviewer's model is down, the queue merges on the automatic checks and the review runs after the merge; the reviewer's MiniMax plan is the reviewer's alone; until it answers, the session holding the CI lands every merge | [§2](../../DESIGN.md) · [§10](../../DESIGN.md) · [§14](../../DESIGN.md) | ● | ● | ● | ● |
| which model the HealthWorld box runs on (off until then), and the test business's JobWorld box for a proof other than GHL's review of the add-on | [§10](../../DESIGN.md) | ● | ● | | |

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
| the review trigger in every active repo | [§8](../../DESIGN.md) | ● | | | |
| the rule harvest moved here, its rule pull requests drafts | [§9](../../DESIGN.md) | ● | | | |
| a cost meter — reviews and model spend per day | [§13](../../DESIGN.md) | ● | | | |
| merges never wait on the model — the model's check, the UNREVIEWED mark, the queue merging on its own workflows' checks and labelling `review-owed` | [§2](../../DESIGN.md) · [§5](../../DESIGN.md) | ● | ● | ● | |
| the late review — a merged `review-owed` pull request reviewed once the model answers; BLOCKING opens a fix issue | [§4](../../DESIGN.md) · [§6](../../DESIGN.md) | ● | ● | | |
| a failed review shown failed on the pull request — today the canonical home's check is the dispatch, green whatever the review does | [§13](../../DESIGN.md) | ● | | | |
