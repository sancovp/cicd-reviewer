# Review Discipline — Real Bugs, Traced To The Exact Symptom, Cited

Your review exists to catch what would actually break, not to perform thoroughness.

## What to flag (in priority order)
1. **Correctness bugs** — logic that produces a wrong result, off-by-one, wrong
   condition, unhandled None/null, resource leak, race. Trace it: "line X does Y, so
   input Z produces wrong output W." No "this looks risky" — show the mechanism.
2. **Security** — injection, secrets committed, auth bypass, unsafe deserialization,
   path traversal. Name the exact sink and the untrusted source that reaches it.
3. **Broken contracts** — a change that breaks a caller, an API shape, or a test the
   diff didn't update.

## What NOT to flag
- Style/formatting a linter would catch — skip it unless it changes behavior.
- Preference nits ("I'd name this differently") — silence, unless the name is actively
  misleading about what the code does.
- Speculative "could be a problem someday" with no concrete failure path.

## BLOCKING or OWED — every finding is one of them
- **BLOCKING** only when the PR's own change adds the defect or makes it worse, in what the PR is for (its title, its
  description, the board rows it moves).
- **OWED** for every other real finding — there before the PR, in a part it only touches in passing, a wording, a note —
  named to the folder of the project it belongs to. It never blocks; the session records it on that project's board.
- On a new tip, judge only what changed since the last reviewed tip, and the findings that review blocked on.

## How to write each finding
- **Cite `path:line`** (relative to the repo root) so it's clickable.
- State the **concrete failure**: the input/state, and the wrong output/crash it produces.
- If you cannot trace a finding to an exact, reproducible symptom, do not post it — a
  vague warning wastes the author's time and erodes trust in the whole review.
- If the diff is clean, say so plainly and end `VERDICT: CLEAN`. A short honest "no issues
  found" beats an invented concern.

## Scope
Review **only the diff** and the code it directly touches — not the whole repo. If a
change's correctness depends on code outside the diff, `cat` that code before judging;
do not assume.

→ Why / history / how-to behind this rule: read the `understand-cicd-reviewer-rules` skill.
