---
name: open-pr-for-branch
description: "Open a pull request for a freshly-pushed branch that has no PR yet. Use when MODE=pr — summarize what the branch changes against the default branch and create the PR with gh pr create."
---

# Open PR For Branch (MODE=pr)

A branch (`$HEAD_REF`) was pushed to `$GITHUB_REPOSITORY` with no open PR. Your job: open
one with a real, useful title and body — not a placeholder.

## Steps

1. **Find the default branch and the change set:**
   ```
   git -C /repo remote show origin | sed -n 's/.*HEAD branch: //p'   # default branch, e.g. main
   git -C /repo fetch origin
   git -C /repo log --oneline "origin/<default>..$HEAD_REF"          # commits this branch adds
   git -C /repo diff --stat "origin/<default>...$HEAD_REF"           # files touched
   ```

2. **Read the diff enough to describe it truthfully** (`git -C /repo diff "origin/<default>...$HEAD_REF"`).
   Summarize what actually changed and why, from the code — do not invent intent.

3. **Check a PR doesn't already exist:**
   ```
   gh pr list --repo "$GITHUB_REPOSITORY" --head "$HEAD_REF" --json number
   ```
   If one exists, say so and stop (do not open a duplicate).

4. **Open the PR:**
   ```
   gh pr create --repo "$GITHUB_REPOSITORY" --head "$HEAD_REF" --base "<default>" \
     --title "<concise real title>" \
     --body "$(summary of the change, bulleted file-level notes, and any risk you noticed)"
   ```
   Title = what the branch does, in one line. Body = a short paragraph + bullets of the
   notable changes; flag anything that looks incomplete or risky (but do not block —
   this is PR creation, review happens separately).

5. Print the PR URL `gh` returns, then say `DONE`.

Per `git-safety`: branch first if you add a commit, never force-push, never target the
default branch's history directly.
