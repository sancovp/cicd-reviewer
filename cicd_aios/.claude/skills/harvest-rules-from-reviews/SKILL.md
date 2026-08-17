---
name: harvest-rules-from-reviews
description: "Distill your own recurring review findings into ONE new rule-candidate and open a PR for it. Use when MODE=harvest — the scheduled self-maintenance run that grows your review discipline from your own review history. The maintainer's merge of your PR is the approval gate."
---

# Harvest Rules From Reviews (MODE=harvest)

The loop you implement: your posted reviews are the finding corpus → a RECURRING class of
finding becomes a RULE-CANDIDATE → you open a PR adding it to your own AIOS rules → the
maintainer's merge is the approval gate → the next image build bakes the rule into every
future review. You propose; the human approves; the pipeline deploys.

## Steps

1. **Gather the corpus** — your recent posted reviews on this repo:
   ```
   gh pr list --repo "$GITHUB_REPOSITORY" --state all --limit 20 --json number,title
   gh api "repos/$GITHUB_REPOSITORY/pulls/<N>/reviews" --jq '.[] | {state, body}'   # per PR
   ```
   Collect every finding (the `path:line — failure` bullets) across all reviews.

2. **Read your CURRENT rules** — `cat` every file in your own `.claude/rules/` — so you
   know exactly what is already covered.

3. **Distill.** A rule-candidate requires a RECURRING class: the same KIND of finding in
   **≥2 distinct reviews** (e.g. two different unguarded-division crashes; two
   secret-in-diff findings), expressible as a reviewable discipline ("when the diff
   touches X, always check Y"), and NOT already covered by an existing rule.
   **If nothing recurs, or it is already covered: do NOT invent a rule.** Report plainly
   "no recurring uncovered finding class — no rule this cycle" and end with DONE. An
   invented rule degrades every future review (same law as "no invented review concern").

4. **Author the candidate** — exactly ONE new file:
   `automation/cicd-reviewer/cicd_aios/.claude/rules/<kebab-name>.md`
   Written in the shape of your `review-discipline` rule (what to flag / what NOT to
   flag / how to write the finding), ending with a `## Provenance` section listing the
   PR numbers + the concrete findings it distills.
   **Write it with bash (your only tool), using a QUOTED heredoc:**
   ```
   cat > /repo/automation/cicd-reviewer/cicd_aios/.claude/rules/<kebab-name>.md <<'EOF'
   ...the rule text...
   EOF
   ```
   Do NOT look for a Write/file tool — there is none. Do NOT call WriteBlockReportTool
   as a checkpoint or progress note: it is the voluntary-HALT tool and ENDS your run;
   use it only if you are genuinely blocked and cannot proceed.

5. **Open the PR** (branch-first, per `git-safety`; commit ONLY that one file):
   ```
   gh auth setup-git 2>/dev/null || true
   DEFAULT=$(gh repo view "$GITHUB_REPOSITORY" --json defaultBranchRef -q .defaultBranchRef.name)
   git -C /repo checkout -b "cicd-rules/<kebab-name>" "origin/$DEFAULT"
   # write the file, then:
   git -C /repo add automation/cicd-reviewer/cicd_aios/.claude/rules/<kebab-name>.md
   git -C /repo -c user.name="cicd-reviewer" -c user.email="cicd-reviewer@users.noreply.github.com" \
     commit -m "cicd rule-candidate: <name> (harvested from own reviews)"
   git -C /repo push origin "cicd-rules/<kebab-name>"
   gh pr create --repo "$GITHUB_REPOSITORY" --head "cicd-rules/<kebab-name>" \
     --title "CICD rule-candidate: <name>" \
     --body "<one-line what the rule catches; the Provenance list (PR numbers + findings); and: merging this PR approves the rule — the next image build bakes it into every future review.>"
   ```
   Print the PR URL.

6. Say `DONE`.

You add exactly ONE new rule file in your own AIOS rules dir and NOTHING else. You never
edit existing rules, never touch code, and NEVER approve or merge your own rule-PR — the
maintainer holds that gate.
