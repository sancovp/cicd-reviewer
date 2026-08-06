# Broken Cross-References — Cited Filenames, Symbol Names, and Doc-Tree Drift

This is the second recurring finding class the reviewer catches across PRs that
the generic `review-discipline.md` and `boundary-input-guards.md` rules
under-represent: the diff cites a **filename**, **symbol name**, **section
anchor**, or **commit / branch ref** as if it exists, but the repo, the
diffed files, or the named function says otherwise. The trap is that the
diff's *prose* is plausible — the cite reads naturally in context — but a
`find /repo -iname <name>` or `grep -R <symbol>` returns nothing, or returns
something with a different shape than the cite claims. A future reader
following the breadcrumb gets nothing.

This is distinct from boundary-input fallthroughs (a runtime crash on the
empty input) and from generic "unhandled null" (a runtime crash on the
absent value). The bug here is *static and declarative*: the diff asserts
something is true of the tree, the tree contradicts it, and nobody notices
until a reviewer follows the trail.

## What to flag

1. **Cited filenames that don't exist in the tree.** A doc (markdown, paper,
   comment, docstring, log line) says "see `FOO.md`" or
   "logs the output to `<dir>/bar.json`" or "this discharge the debts logged
   in `BAZ.md` Part I §2/§5" — and `find /repo -iname "<pattern>"` returns
   nothing. Trace it with the exact command so the finding is reproducible:
   "the cited file `KNOBS-ARE-MINESPACE.md` does not exist anywhere in `/repo`
   (verified by `find /repo -iname '*KNOBS-ARE*'`); the diff's claim that
   this paper 'discharges the proof debts logged in' it is unverifiable."

2. **Cited artifact paths that exist on an orphan commit but not on the
   merge target.** The doc says "the cycle-1 artifacts are
   `BigBrainHead-{OpenRim,HalfDome,FullDome}.glb`" but the artifacts only
   exist on a commit that was dropped before `main` — they were never on
   `main`, only on an experimental branch commit. The diff's "this PR
   supersedes / removes / produces X" wording is unverifiable against the
   tree the PR actually targets.

3. **Symbol-name drift between prose and code.** The doc claims a function
   is named `build_dome_v3(coverage, ...)` or accepts a parameter
   `coverage`, but the actual function in the diff is `build_dome(rx, ry,
   rz, base_z)` — different name, different signature. A future maintainer
   who reads the doc and searches for the cited symbol won't find it, or
   will find a different function and assume the rename was undocumented.
   Trace it: "doc says `build_dome_v3(coverage, ...)`; code defines
   `build_dome(rx, ry, rz, base_z)` at `path:line` — the symbol names do
   not match."

4. **Prose that implies a tree mutation the diff didn't make.** "REMOVED
   (superseded gray rocks)" wording in a section the diff also touches
   implies the diff removed those artifacts; but `git -C /repo ls-files |
   grep "gray rocks"` shows they were never present on the merge target.
   Cite the exact prose phrase and the exact `git ls-files` (or `find`)
   result so the reviewer can verify on a clean tree.

5. **Type / signature annotations that contradict the code.**
   `-> List[dict]` annotated on a function that returns
   `Tuple[List[dict], Dict[str, Any]]` — the annotation lies; a future
   caller who reads only the annotation writes a single-return caller that
   unpacks garbage. (This is the static-doc-subset of the broader doc-vs-code
   drift class; included because it's the same symptom and the same fix.)

## What NOT to flag

- **Linter-level drift** — missing trailing newline, capitalisation in a
  comment, single-vs-double-quote consistency in prose. These don't change
  reader behavior at the structural level.
- **Stale prose that just describes the old behavior** when the doc itself
  isn't a breadcrumb (no future reader would follow it to a cited file).
  Only flag when the prose *asserts a relationship to a named tree artifact*.
- **Cites inside a sandbox / fixture file marked DO NOT MERGE** — those
  files are the test payload, not the contract. Still surface the cite
  loosely so the loop runs, but mark non-blocking and don't request changes.
- **Drift where the doc and code are both inside the diff and the diff
  updates both in the same commit.** That's a rename, not a cite-break —
  the diff is self-consistent, the tree just transitions.
- **Speculative "what if someone cites this later"** — only flag cites
  the diff *actually makes*. A doc that names its own sub-sections
  (§1, §2, §A) doesn't need a find-check; only cites to *external* files
  or symbols do.

## How to write each finding

- **Cite the doc location** (`path:line` of the prose that makes the cite)
  AND the **exact command that proves the cite is broken** (`find /repo
  -iname "<pattern>"` returned nothing; `grep -n "<symbol>" <files>`
  returned only the cite itself; `git -C /repo ls-files | grep "<name>"`
  returns empty).
- State the **concrete reader impact**: "a reviewer or future reader
  following the breadcrumb gets nothing." Do not speculate beyond the
  reader-follows-the-cite case.
- If the cite is to a file that *does* exist but the cited *content* is
  wrong (the file exists, but the cite's claim about what it contains is
  false), say so explicitly: "the file exists at `<path>`, but it contains
  `<X>`, not the `<Y>` the cite asserts."
- If the cite is in a changelog / history doc that the diff explicitly
  disclaims ("this is a historical record, not a current-state claim"),
  note the disclaimer and mark non-blocking.
- **Do not propose the fix** unless the fix is mechanical and obvious
  (drop the cite). For deeper drift (the cited file genuinely should exist
  with content the paper asserts), leave the fix to the author — naming
  the shape of the missing content is fine, but don't write the file for
  them.

## Sweep order

On every PR that touches documentation, paper prose, README, status /
state ledger, or a comment / docstring that names another file or
symbol, run this sweep before approving:

  1. For every `see <file>`, "in `<file>`", "logged in `<file>`",
     "discharges the debts in `<file>`" form in the diff, run
     `find /repo -iname "<basename or pattern>"` and confirm the file
     exists on the merge target (not just on a sibling branch or orphan
     commit).
  2. For every `function_name(`, `class_name`, `<symbol>.<method>`,
     `<module>.<attr>` reference in the prose, run
     `grep -rn "<symbol>" /repo --include='*.py' --include='*.ts' \
     --include='*.tsx' --include='*.js' --include='*.go' --include='*.rs'`
     (or the repo's source-language set) and confirm the symbol exists
     at the cited signature / shape.
  3. For every "REMOVED", "superseded by", "replaces", "this PR adds X"
     prose claim, run `git -C /repo ls-files | grep "<named artifact>"`
     and confirm the artifact's existence-state matches the claim.
  4. For every type annotation the diff adds or modifies, spot-check at
     least the function bodies the diff's tests call into — if the
     annotation says one shape and the function returns another, that's
     the broken-cite pattern at the type level.
  5. If the diff is a paper or proof that "discharges the proof debts"
     or "sharpens theorem T" or "instantiates the map exhibited by
     `<other-doc>`", find that other doc by name and confirm it exists
     with the cited content.

## Provenance

Distilled from these reviews on sancovp/sanctuary-revolution-alpha:

- **PR #16** (`proofs: cb_knob_domain_consistency — the knob domain paper`) —
  two cite-broken findings in one review, both CHANGES_REQUESTED-worthy.
  - `cb_knob_domain_consistency.md:10` cites `KNOBS-ARE-MINESPACE.md`
    Part I §2/§5 and Part II.2 as the source of the proof debts being
    discharged; `find /repo -iname '*KNOBS-ARE*'` returns nothing.
  - `cb_knob_domain_consistency.md:25` abstract cites
    `KNOB-MINESPACE-JOIN.md`'s `KernelAdapter` as the instantiation map
    the proof takes as given; `find /repo -iname '*knob-minspace-join*'`
    returns nothing.

- **PR #28** (`bigbrain: BigBrainHead part — GEN cycle 1`) — three
  doc-vs-tree drift findings, all on the lane-state doc that accompanies
  the new GLB.
  - `bigbrain_states.md` header table row 5 cites
    `BigBrainHead-{OpenRim,HalfDome,FullDome}.glb` as cycle-1 artifacts;
    those blobs exist only on orphan commit `1703b82f`, never on `main`.
  - Same doc's `§ GEN CYCLE 1` describes a `build_dome_v3(coverage, ...)`
    function; the actual function in the diff is `build_dome(rx, ry, rz,
    base_z)` — different name and signature.
  - README's "REMOVED (superseded gray rocks)" wording implies this PR
    removed those GLBs; `git -C /repo ls-files | grep "gray rock"`
    returns nothing on `main` — the removal never happened on the merge
    target.

Both reviews surfaced the same shape of defect (prose asserts a
relationship to a tree artifact; the tree says otherwise) using the same
verification method (`find /repo -iname <pattern>`). The class is
recurring and distinct from runtime-crash patterns.
