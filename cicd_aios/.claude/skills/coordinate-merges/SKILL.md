---
name: coordinate-merges
description: "Decide the merge order of pull requests that were each reviewed CLEAN but touch the same files, and hold any that contradict another. Use when MODE=coordinate."
---

# Coordinate Merges (MODE=coordinate)

You sit ABOVE the reviews. Each pull request in `COORD_INPUT` was reviewed CLEAN on its own; they overlap in files,
so each review saw only itself. Your job is the one thing no single review can see: how they go TOGETHER.

## Steps

1. Read every pull request's diff and description:
   ```
   gh pr view <n> --repo "$GITHUB_REPOSITORY" --json title,body
   gh pr diff <n> --repo "$GITHUB_REPOSITORY"
   ```
2. Look only at how they interact, on the files they share:
   - one UNDOES or CONTRADICTS another (states the opposite design, reverts a fix, renames what the other uses)
   - combined they BREAK (both change one function's contract; one deletes what the other calls)
   - one DEPENDS on another (merge that one first)
3. Decide:
   - **order** — every pull request you do not hold, in the order they should merge (dependencies first; else
     the one the others build on; else oldest first)
   - **hold** — only a pull request with a real interaction problem, each with ONE sentence naming the other
     pull request and the exact conflict. Two pull requests that touch the same file without interacting are NOT a
     reason to hold anything — order them.
4. Write ONLY this JSON to `/out/decision.json`, with a quoted heredoc:
   ```
   cat > /out/decision.json <<'EOF'
   {"order": [12, 9], "hold": [{"pr": 10, "reason": "#10 restores the 'own deployment' wording #12 replaces"}]}
   EOF
   ```
5. Say `DONE`.

You never merge, push, comment or post a review in this mode. The merge queue acts on your file: it merges the first
in your order, re-reviews the rest against the new main, and comments your reason on each held pull request.
