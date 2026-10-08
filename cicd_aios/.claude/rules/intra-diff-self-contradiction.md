# Intra-Diff Self-Contradiction — The Diff Disagrees With Itself

This is the third recurring finding class the reviewer catches across PRs
that the existing rules (`review-discipline.md`, `boundary-input-guards.md`,
`broken-cross-references.md`) under-represent: **two pieces of code or
prose introduced in the same diff disagree with each other on the same
fact, the same input, or the same shape.** A reader who sees only one of
the two pieces is misled; a reader who sees both is left to guess which
is the truth. The defect is *intra-diff* — nothing outside the diff is
required to expose it, and the diff itself is the source of the
contradiction.

This is distinct from `broken-cross-references` (which is about cites to
*external* files or symbols that do not exist), and from
`boundary-input-guards` (which is about runtime crashes on empty input).
It is also distinct from generic "stale prose" — the prose here is not
stale, it is *new*, and it contradicts the other new prose / code that
ships alongside it in the same commit.

## What to flag

1. **Two sibling functions in the same file disagree on the same input
   shape.** Example: one function defaults a missing dict key to `0`,
   another sibling function on the same input throws — a future caller
   that handles one case and passes the same input to the other will
   be wrong by construction. Trace it with the exact line numbers and
   the exact input shape that triggers the divergence.

2. **Two adjacent prose sections in the same doc contradict each other
   on the same fact.** Example: a header table row cites three GLB
   filenames as "cycle-1 artifacts" while the section immediately below
   the table says "REMOVED (superseded)" — the table is wrong *by
   itself*, but the contradiction is only visible when the reader
   compares the two. A future reader following the table row alone
   searches for files that don't exist.

3. **A doc claims one function signature and another section of the
   same doc uses a different signature for the same function.** Example:
   one section names `build_dome_v3(coverage, ...)` while a later
   section uses the actual `build_dome(rx, ry, rz, base_z)` — the doc
   contradicts itself on the symbol it describes. (When the contradiction
   crosses to *external* symbols — names a function that does not exist
   in the tree — that is `broken-cross-references` and goes there
   instead.)

4. **A verification/measurement row mixes units in adjacent columns.**
   Example: a single row reads `thigh 1.0 rad pk-pk (57°) / knee 0.74
   (42°) / arm 0.42` where the first two are degree equivalents of the
   same rad-pk-pk amp and the third is a raw amp coefficient in
   different units — readers parsing the row as if all three columns
   share a unit get nonsense.

5. **The header comment of a function describes one behavior and the
   function body implements another, both in the same diff.** Example:
   a function header calls itself "the teeth-bearing predicate" while
   the body returns a value computed by a check whose "fail" branch
   is unreachable on real inputs (a join across incompatible key
   representations, or a constant default that masks every failure
   mode). The contradiction is between intent-stated and behavior-shipped.

6. **Two diff-introduced error messages, default values, or thresholds
   for the same code path disagree without comment.** Example: function
   A returns `[]` on an empty input while function B for the same
   logical operation throws; no comment explains the split. A reviewer
   cannot tell whether the divergence is intended.

## What NOT to flag

- **Linter-level inconsistencies** — single-vs-double-quote, missing
  trailing newline, capitalisation in a comment. These don't change
  reader behavior at the structural level.
- **Drift between code and an OLDER doc section that the diff did not
  touch** — that is `broken-cross-references` (the cite predates the
  diff). This rule fires only when *both* contradicting pieces are
  introduced by the same diff.
- **Honest residues disclosed by the author in the same PR** — when
  the PR body or a comment in the diff explicitly says "this is a
  known mismatch, see <issue>", the contradiction is surfaced by the
  author and the loop has already run. Still name the residue so the
  follow-up is visible, but mark non-blocking.
- **Two functions that legitimately do different things on the same
  input** (e.g. one aggregates, the other validates, and "missing key"
  means "no value to aggregate" vs "no value to validate" — different
  semantics, documented or obvious). Cite this only if the divergence
  is undocumented and a future caller would plausibly mistake one for
  the other.
- **Renames inside the diff that update both call sites and the
  definition in the same commit** — that is a rename, not a
  contradiction. The doc/codes transition together and end in one
  consistent state.
- **Speculative "what if someone reads only the table"** — only flag
  contradictions the diff actually ships. A table that the diff does
  not touch does not need a re-read.

## How to write each finding

- **Cite both `path:line` locations** that contradict each other (the
  diff made both). Quote the exact prose / code that disagrees, side
  by side, so the reviewer can verify on a clean tree without reading
  the whole file.
- State the **concrete reader impact**: "a reviewer or future reader
  who sees only `<section X>` concludes `<wrong fact>`; a reader who
  sees only `<section Y>` concludes `<different wrong fact>`; both are
  misled, and the contradiction is invisible unless both are read."
  Do not speculate beyond the two-reader case.
- If the contradiction is between *intent* (a comment / docstring /
  table header) and *behavior* (the function body / the actual
  measurement), say so explicitly and note which side is the source
  of truth — usually the behavior, but flag when the intent is the
  contract and the behavior is wrong (e.g. a predicate whose header
  promises "fails loudly on disagreement" but whose body can never
  disagree).
- If the diff is honestly trying to flag the contradiction itself
  (e.g. a `// TODO: align with coboundary` next to one of the two
  sites), note the TODO and mark non-blocking.
- **Do not propose the fix** unless the fix is mechanical and obvious
  (rename one column header to its real unit; replace a default-0
  with a throw that matches the sibling; delete the obsolete table
  row). For deeper harmonization (two functions that should share an
  abstraction but don't), leave the fix to the author — naming the
  shape of the missing abstraction is fine, but don't write it for
  them.

## Sweep order

On every PR, after reading the diff, run this mental sweep before
approving:

  1. **Sibling functions in the same file.** For every function the
     diff adds or modifies, scan its siblings (functions in the same
     module that operate on the same input shape) and ask: do they
     agree on what happens when that input is missing / empty / wrong?
  2. **Adjacent prose in the same doc.** For every doc section /
     paragraph / table row the diff touches, scan the sections
     immediately above and below for claims that touch the same fact,
     the same file, the same function, or the same metric. Do they
     agree?
  3. **Docstring vs body.** For every function the diff adds or
     modifies, does the docstring's behavior match the body's
     behavior? In particular: do predicates whose headers claim
     "fails on X" actually fail on X on real inputs, or do they
     pass by construction?
  4. **Units in adjacent columns of the same row.** For every
     verification / measurement / manifest row the diff adds or
     modifies, do all the columns share a unit, or does the row
     silently mix degrees / radians / coefficients / counts?
  5. **Error / default / threshold for the same code path.** For
     every error message, default value, or threshold the diff adds
     or modifies, scan the immediate neighborhood for a parallel
     site that handles the same input differently. If found, is the
     divergence documented?

## Provenance

Distilled from these reviews on sancovp/sanctuary-revolution-alpha:

- **PR #26** (`preserve: snapshot accumulated monorepo working tree
  (2026-07-16)` — preservation snapshot, reviewed at the only
  coherent new logic on the branch) — three intra-diff
  self-contradictions, one blocking, two non-blocking.
  - `base/crystal-ball-alpha/lib/crystal-ball/sheaf.ts:542-543` —
    the `Cs3` key-join check `validTree.has(o.coordinate)`
    structurally cannot fail: `validTree` holds kernel NodeId
    tokens (`"a"`, `"8"`, `"1"`) while `obstruction[i].coordinate`
    is sourced as a dotted path (`"1.2.3"`). The two
    representations never collide, so the predicate always passes
    on real data and the "teeth-bearing" branch the header comment
    promises is unreachable. The synthetic test passes by fixing
    the bug into the test data (`coordinate: '1'`), not into the
    predicate. **CHANGES_REQUESTED-worthy.** The function's own
    header calls this exactly the "key join" whose job is to
    "FAIL loudly when Ш flags a tree node as non-closing" — the
    header vs the body are the contradiction.
  - `sheaf.ts:192` (`dirichletEnergy`) defaults a missing node
    opinion to `0` via `(x.get(e.v) ?? 0) - (x.get(e.u) ?? 0)`,
    while the sibling `coboundary` at `sheaf.ts:181` throws on the
    same missing-key case. Two functions in the same file, same
    input shape, divergent contract, no comment explaining the
    split. Non-blocking — every caller today builds a complete
    `Map` — but latent and worth aligning.
  - The PR body itself is the contradiction host: 1 squashed
    commit, 1225 files, where a "follow-up task splits this into
    per-feature PRs" is named as the real review surface, but
    "the dirichletEnergy / coboundary inconsistency above (and
    any similar small contracts) [will be] invisible to that
    follow-up review because they're already absorbed into the
    snapshot". The class recurs across the diff's own shape.

- **PR #28** (`bigbrain: BigBrainHead part — GEN cycle 1`) — three
  intra-diff self-contradictions in `bigbrain_states.md`, the
  lane-state doc that accompanies the new GLB.
  - Header table row 5 cites
    `BigBrainHead-{OpenRim,HalfDome,FullDome}.glb` as cycle-1
    artifacts; the § CYCLE 1b section immediately below says
    "REMOVED (superseded)". The table contradicts the section
    that follows it. (Some of this is also a
    `broken-cross-references` hit — the cited blobs exist only on
    orphan commit `1703b82f`, never on `main` — but the table vs
    section contradiction is intra-doc, not tree-vs-doc, and
    belongs here.)
  - Same doc: § GEN CYCLE 1 describes a
    `build_dome_v3(coverage, ...)` function; § CYCLE 1b — Honest
    residue uses the correct knob names (`dome_rz`, `base_z`).
    The doc contradicts itself on the symbol it describes.
  - README's "REMOVED (superseded gray rocks)" wording implies
    the PR removed those GLBs; it didn't, they were never on
    `main`. (Again, partly a `broken-cross-references` hit on the
    tree-vs-prose axis; the intra-diff aspect is that the README
    claim and the diff's actual effect disagree on the same
    fact.)

- **PR #97** (`RAISE WALK_GAIT (0.42/0.55→0.50/0.74) — the calm
  walk was a shuffle`) — one intra-diff self-contradiction in the
  state doc that accompanies the amplitude raise.
  - `armature_lane_states.md` L100 — the new verification row
    mixes units in adjacent columns: `thigh 1.0 rad pk-pk (57°)
    / knee 0.74 (42°) / arm 0.42`, where the first two are
    degree equivalents of the same rad-pk-pk amp and the third
    is a raw amp coefficient (not a degree), while the
    comparison `RUN 77°/56°/31°` immediately beside it is
    pk-pk degrees. Easy to misread in the same paragraph.
  - (Plus a related but distinct intra-diff note: the in-code
    comment at `blender_side/armature.py:37-40` was written for
    the original 0.42/0.55/0.30/0.10 values and reads stale at
    the new 0.50/0.74/0.42/0.12 — the comment and the constants
    disagree. Direction still holds, hence non-blocking, but
    the same shape: comment-introduced-by-the-diff and
    behavior-introduced-by-the-diff disagree on the same fact.)

All three reviews surfaced the same shape of defect (the diff ships
two pieces that disagree with each other on the same fact, input,
or unit, with no comment reconciling them) using the same
verification method (read both sides, quote both, name the reader
who sees only one). The class is recurring and distinct from
the two existing rules.
