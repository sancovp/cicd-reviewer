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
| the review trigger in every active repo | [§8](../../DESIGN.md) | ● | | | |
| the rule harvest moved here, its rule pull requests drafts | [§9](../../DESIGN.md) | ● | | | |
| a cost meter — reviews and model spend per day | [§13](../../DESIGN.md) | ● | | | |
