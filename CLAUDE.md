# automation/cicd-reviewer — the CI

What this dir is FOR: the CI that gets work from a branch onto its default branch — the reviewer (an AI that reviews
one pull request and ends with a verdict), the coordinator (an AI above the reviews, called when ready pull requests
overlap), the merge queue (`merge_queue.py`, the only thing that merges), and the daily sweep (`sweep.py`) over every
repository. `cicd_aios/` is the reviewer agent's own AIOS (its identity, rules and skills, baked into its image);
`.github/workflows/` runs it on the public `sancovp/cicd-reviewer`, where this directory is published.

Canon: [`DESIGN.md`](DESIGN.md) · the board [`.claude/rules/cicd_reviewer_states.md`](.claude/rules/cicd_reviewer_states.md)
(its `## OPEN` table waits on *USER*) · the stack [`.claude/rules/21-architecture-diagrams.md`](.claude/rules/21-architecture-diagrams.md)
· history `CHANGELOG.md`. Edit here, never in the public repo. Tests: `python3 tests/test_merge_queue.py` ·
`python3 tests/test_sweep.py` · `python3 tests/test_ci_agent.py`.
