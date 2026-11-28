---
name: review-pr-diff
description: "WHAT: review a pull request's diff — or, on a new tip, only what changed since the last reviewed one — and post the review with gh, BLOCKING only on the PR's own defect. WHEN: MODE=review or MODE=review-merged."
---

# Review PR Diff (MODE=review · MODE=review-merged)

**In full:** Review a pull request and post the review. Use when MODE=review — a PR was opened or updated and you must
read its diff against the base branch, find real bugs, and post a review with gh — and when MODE=review-merged, the late
review of a PR merged while the model was down, posted as a comment.

You are reviewing PR `#$PR_NUMBER` on `$GITHUB_REPOSITORY`: head `$HEAD_REF` against base `$BASE_REF`.

## A REVIEW CONVERGES

A review that blocks on everything it can find never ends: each fix opens a fresh review of the whole PR, which finds
the next edge somewhere else. So:

- **BLOCKING** is only a real defect that the PR's own change adds or makes worse, in what the PR is for — the version it
  carries, as its title, its description and its project's board name it.
- **OWED** is every other finding: a defect that was there before, one in a part the PR only touches in passing, a
  wording, a note. It never blocks. Name the folder of the project it belongs to; the session that owns the PR records it
  on that project's board (a late review's go into an issue the CI opens).
- **A new tip is reviewed for what changed since the last reviewed tip**, together with the findings that review blocked
  on. Your prompt says when this is so, and names the tip and the findings. Do not review the rest of the PR again: a
  defect you see outside what changed is OWED.

## Steps

⛔ **YOUR RUN IS DONE WHEN YOUR REVIEW IS POSTED, AND NOT BEFORE.** You are continued in this same conversation until a
review ending in its verdict line is on the pull request. Read everything you need to judge it; then post.

1. **Read what the PR is for.** `gh pr view "$PR_NUMBER" --repo "$GITHUB_REPOSITORY" --json title,body`, then the board
   of the project it changes (`cat /repo/<the project>/.claude/rules/*_states.md`): the rows it moves are what it is for.

2. **Get the diff.**
   - The whole PR (base..head, so you see only what this PR changes):
     ```
     git -C /repo fetch origin "$BASE_REF" "$HEAD_REF"
     git -C /repo diff "origin/$BASE_REF...origin/$HEAD_REF"
     ```
     If that range is empty, fall back to `git -C /repo diff "origin/$BASE_REF" HEAD`. For a merged PR:
     `gh pr diff "$PR_NUMBER" --repo "$GITHUB_REPOSITORY"`.
   - A new tip, when your prompt names the last reviewed tip `<sha>`: what changed since that tip —
     `git -C /repo diff <sha> HEAD`. Your prompt names a tip only when no merge of the default branch came in since it,
     so every line of that diff is the PR's own.

3. **Read what you need.** For any changed line whose correctness depends on code not in the diff, `cat /repo/<file>`
   to see it. Do not judge from the hunk alone when context matters.

4. **Find real findings** per the `review-discipline` rule: correctness → security → broken contracts. Each finding =
   `path:line` + the concrete failure (input → wrong output/crash). Drop anything you can't trace to an exact symptom.
   Then class each one BLOCKING or OWED, as above. On a new tip, write each finding the last review blocked on again:
   fixed ⇒ a `- FIXED:` line; not fixed ⇒ it stays a `- BLOCKING:` line.

5. **Post the review** with `gh` — MODE=review on the PR, MODE=review-merged as a comment on the merged PR:
   ```
   gh pr review "$PR_NUMBER" --repo "$GITHUB_REPOSITORY" --comment --body-file <file>
   gh pr comment "$PR_NUMBER" --repo "$GITHUB_REPOSITORY" --body-file <file>      # MODE=review-merged
   ```
   GitHub refuses `--approve` and `--request-changes` from the account that owns the PR, so it is always a comment.
   Write the body as a short summary line, then one line per finding, each exactly:
   ```
   - BLOCKING: `path:line` — <failure>
   - OWED (<the folder of the project it belongs to>): `path:line` — <finding>
   - FIXED: `path:line` — <what fixed it>          # only on a new tip, for a finding the last review blocked on
   ```
   Never write the BLOCKING mark on a finding that is fixed or owed: a `- BLOCKING:` line under `VERDICT: CLEAN` is read
   as BLOCKING by every reader, and your run counts it as no result. If there is nothing: one line, "No issues found."

   ⛔ **THE LAST LINE OF EVERY REVIEW IS THE VERDICT, EXACTLY ONE OF:**
   ```
   VERDICT: CLEAN
   VERDICT: BLOCKING
   ```
   BLOCKING = at least one BLOCKING finding. CLEAN = none; OWED findings may sit above it. Nothing after it. The merge
   queue reads this line and merges the pull request on CLEAN, the PR watch reads the OWED lines, and the next review
   reads the BLOCKING lines — so a missing or misspelled verdict leaves the work unmerged, and a finding not on its own
   line is lost.

6. Say `DONE`.

You do NOT modify code, push, or open PRs in this mode (see `git-safety`). Read + review + post only.
