---
name: review-pr-diff
description: "Review a pull request's diff and post the review. Use when MODE=review — a PR was opened or updated and you must read its diff against the base branch, find real bugs, and post a review with gh."
---

# Review PR Diff (MODE=review)

You are reviewing PR `#$PR_NUMBER` on `$GITHUB_REPOSITORY`: head `$HEAD_REF` against base `$BASE_REF`.

## Steps

1. **Get the diff** (base..head, so you see only what this PR changes):
   ```
   git -C /repo fetch origin "$BASE_REF" "$HEAD_REF"
   git -C /repo diff "origin/$BASE_REF...origin/$HEAD_REF"
   ```
   If that range is empty, fall back to `git -C /repo diff "origin/$BASE_REF" HEAD`.

2. **Read what you need.** For any changed line whose correctness depends on code not in
   the diff, `cat /repo/<file>` to see it. Do not judge from the hunk alone when context
   matters.

3. **Find real findings** per the `review-discipline` rule: correctness → security →
   broken contracts. Each finding = `path:line` + the concrete failure (input → wrong
   output/crash). Drop anything you can't trace to an exact symptom.

4. **Post the review** with `gh`. Approve if clean; request changes if there are real
   correctness/security findings; otherwise comment:
   ```
   gh pr review "$PR_NUMBER" --repo "$GITHUB_REPOSITORY" \
     --comment --body "$(review markdown here)"
   # or --approve (clean) / --request-changes (real blocking findings)
   ```
   Write the body as a short summary line, then a bulleted list of findings, each
   `- \`path:line\` — <failure>`. If clean: one line, "No issues found — approving."

5. Say `DONE`.

You do NOT modify code, push, or open PRs in this mode (see `git-safety`). Read + review + post only.
