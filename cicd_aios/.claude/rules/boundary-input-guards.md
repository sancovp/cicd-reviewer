# Boundary Input Guards — Empty, Zero, None, and Lookup Fallthroughs

## What to flag
1. **Direct arithmetic on length/size without a zero guard** — any
   `sum(...) / len(...)`, `total / count`, `mean(values)`, `average(xs)`,
   `percent(done, total)` form where the divisor can be 0. Trace: "with
   empty `xs`, this raises `ZeroDivisionError: division by zero`; with no
   guard, every caller that passes an empty collection crashes."
2. **Indexing into a possibly-empty sequence** — `lines[0]`,
   `content.splitlines()[0]`, `tokens[N]`, `args.first()`, etc. where the
   sequence may be empty (empty input, empty file, no matches). Trace:
   "with empty input, this raises `IndexError: list index out of range`."
3. **Subscript into a possibly-missing dict key** — `d["x"]` or even
   `d.get(...)["x"]`-style chains when the key may be absent. Trace:
   "with key missing, this raises `KeyError: 'x'`; consider `.get("x")`
   with a sentinel or an explicit `in` check."
4. **Functions that return `None`/empty to signal "not found"** when
   callers in scope (or reasonably foreseeable) will then dereference the
   result. Trace: "with no matching element, this returns `None`; caller
   `result.get("name")` then raises `AttributeError: 'NoneType' object
   has no attribute 'name'`." Prefer raising a typed exception or returning
   an explicit sentinel the caller must check.
5. **`open(path)` / file handles without `with`** in code that runs in any
   non-trivial loop or long-lived process — FD leak that surfaces as
   `OSError: [Errno 24] Too many open files` only after the limit is hit
   (easy to miss in tests, always latent).

## What NOT to flag
- Linter-level "missing newline at EOF" or `== None` vs `is None` style —
  skip; they do not change correctness at runtime.
- "Add a guard just in case" — only flag if you can name the **concrete
  empty/zero/missing-key input** that the diff actually reaches this code
  path with. No speculative "someone might call this with `[]` someday."
- Pure getters whose contract is documented as "raises on missing key"
  (e.g. `Mapping.__getitem__`). That's the spec, not a bug.
- Fixture files explicitly marked DO NOT MERGE / smoketest — they are
  *meant* to exercise the crash. Still cite them so the loop runs, but
  mark non-blocking.

## How to write each finding
- **Cite `path:line`** (relative to the repo root).
- State the **concrete boundary input** and the **exact exception** the
  diff will raise on that input. "Line X averages `nums`; with `nums == []`,
  this raises `ZeroDivisionError: division by zero`" — not "could crash
  on empty input."
- If the diff has no caller in scope AND no caller is reasonably
  foreseeable, say so and mark non-blocking. Latent defects are
  borderline; be honest.
- If the diff is clean on this dimension, do not invent a finding. The
  class is common, not universal.

## Sweep order
On every PR, after reading the diff, run this mental sweep before
approving:

  1. Every function the diff adds or modifies: what does it do on `[]`,
     `""`, `{}`, `0`?
  2. Every arithmetic expression involving division / modulo / mean: is
     the denominator guarded or knowable to be > 0?
  3. Every `.splitlines()[N]`, `list[0]`, `dict[K]`: is the index/key
     knowable to exist?
  4. Every function whose return value a caller will then method-call or
     subscript: does it ever return `None` or an empty container as a
     "not found" signal?
  5. Every `open()` in non-trivial code: is it `with`-bound?

→ Why / history / how-to behind this rule: read the `understand-cicd-reviewer-rules` skill.
