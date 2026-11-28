#!/usr/bin/env python3
"""THE PR WATCH — what a session runs in the background while the CI takes its pull request to the default branch.

The harness wakes a session only when a background task EXITS; a line a running watch prints is never seen. So this
watch exits — once, with one line saying what to do — the moment the pull request needs the session or is done, and it
always exits:

  MERGED     on the default branch (with --expect-head: at that commit, or exit 4 — carry the rest in a new PR)
  CLOSED     closed without merging
  CONFLICT   GitHub cannot merge it: merge the default branch in, push
  BLOCKING   the reviewer's verdict on the exact tip: fix, push
  REVIEW-FAILED  the review trigger failed at the exact tip — no run there succeeded or is still running, the last
             one failed — and no verdict is on the tip: no review is coming — re-run it when GitHub failed to start it;
             jobs refused for the account's billing make the session the CI (DESIGN §5 THE QUEUE BY HAND)
  REVIEW-STALLED the review trigger's run at the exact tip has sat queued STALL_AFTER_MIN minutes with no job started,
             and no verdict is on the tip: GitHub stalls a run this way and will not cancel it, so no review is coming
             from it — start a fresh run (the pull request marked draft, then ready)
  COMMENT    a new comment (the queue's conflict or hold notice, a person): read it — a deploy preview's status
             comment is not one: it is posted on every pull request and never asks the session for anything
  PUSHED     the tip moved under the watch: someone else pushed (with --expect-head, a tip past the one expected)
  TIP-UNSEEN with --expect-head, GitHub still shows another tip after EXPECT_WAIT_POLLS polls: the push may never have
             landed — check it before watching again
  TIMEOUT    still waiting after --max-hours: it says where it stands; the session decides whether to watch again
  GH-DOWN    gh failed on every try for --max-failures polls in a row

With --expect-head it waits until the pull request's tip is that commit before it judges a verdict, a conflict or a
review run: right after a push GitHub can still show the old tip, and the old tip's verdict is not about the push. A
MERGED or CLOSED pull request exits whatever its tip; a tip that moves to a third commit exits PUSHED, and the wait ends
TIP-UNSEEN after EXPECT_WAIT_POLLS polls, so it never hides the pull request for hours.

Every line names the OWED findings of the newest verdict on the tip (DESIGN §11), and MERGED's line says to record each
on the board of the project it names, as work on the default branch. They are never an exit of their own: a CLEAN
verdict merges at once, so a push to carry them would race the merge, and a watch started again on the same tip would
stop on them again.

It checks the pull request BEFORE it waits: a pull request already merged, closed, conflicting or blocked exits at
once — a watch started after the event it waits for never sees a change, and would run until killed. It reads the
review trigger's run at the tip as well as the reviews: a run that failed posts no verdict, and a watch reading only the
reviews waits on it until its cap. A CLEAN verdict and a mergeable state that reads UNKNOWN for a poll are not actions:
the queue moves a CLEAN pull request, and UNKNOWN is GitHub still computing.

  python3 pr_watch.py <number> [--repo owner/name] [--expect-head <sha>] [--interval 60] [--max-hours 4]
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

from sweep import VERDICT_BLOCKING, gh_json, verdict_of

# a finding the review owes to a project's board, one line each (ci_agent.OWED_MARK)
OWED_MARK = "- OWED"

# deploy previews post a status comment on every pull request; none of them asks the session for anything
PREVIEW_BOTS = {"cloudflare-workers-and-pages"}

# the canonical home's one trigger into the CI (DESIGN §3); a repository without it has no run to read
REVIEW_TRIGGER = "CICD Review on PR"
# a trigger run that ended these ways dispatched no review. `cancelled` is not one: the trigger's concurrency group
# cancels a run that a newer one superseded, and that says nothing about whether a review is coming
REVIEW_FAILED = {"failure", "startup_failure", "timed_out", "action_required"}
# a trigger run starts its job within a minute or two; one still queued this long with no verdict on the tip has stalled
# (#2497's two runs sat queued four hours, and GitHub answered a cancel of either that it was completed)
STALL_AFTER_MIN = 20
# GitHub shows a pushed tip within a poll or two; still showing another after this many, the push may never have landed
EXPECT_WAIT_POLLS = 10

EXIT = {"MERGED": 0, "CLOSED": 0, "CONFLICT": 2, "BLOCKING": 2, "TIP-UNSEEN": 2, "REVIEW-FAILED": 2, "REVIEW-STALLED": 2,
        "COMMENT": 2, "PUSHED": 2,
        "TIMEOUT": 3, "HEAD-MISMATCH": 4, "GH-DOWN": 5}


@dataclass(frozen=True)
class Snap:
    state: str            # OPEN · MERGED · CLOSED
    mergeable: str        # MERGEABLE · CONFLICTING · UNKNOWN
    head: str
    verdict: Optional[str]
    comments: int
    review_failed: Optional[str] = None   # how the trigger's deciding run at the tip failed, else None
    review_run_id: Optional[int] = None
    review_stalled: Optional[int] = None  # the minutes the deciding run has sat queued, once that is STALL_AFTER_MIN
    owed: int = 0                         # the OWED findings of the newest verdict on the tip


def snap_of(pr: dict) -> Snap:
    """A `gh pr view --json state,mergeable,headRefOid,reviews,comments` answer, plus `reviewRun` (the trigger's latest
    run at the tip, from `review_run`), reduced to what the watch decides on."""
    head = pr.get("headRefOid") or ""
    verdict, owed = None, 0
    for rv in sorted(pr.get("reviews") or [], key=lambda r: r.get("submittedAt") or ""):
        if ((rv.get("commit") or {}).get("oid") or "") == head and verdict_of(rv.get("body") or ""):
            verdict = verdict_of(rv.get("body") or "")
            owed = sum(1 for l in (rv.get("body") or "").splitlines() if l.strip().startswith(OWED_MARK))
    comments = [c for c in pr.get("comments") or []
                if ((c.get("author") or {}).get("login") or "") not in PREVIEW_BOTS]
    run = pr.get("reviewRun") or {}
    failed = None
    if run.get("status") == "completed" and run.get("conclusion") in REVIEW_FAILED:
        failed = run.get("conclusion")
    queued = run.get("queued_min") if run.get("status") == "queued" else None
    stalled = queued if queued is not None and queued >= STALL_AFTER_MIN else None
    return Snap(pr.get("state") or "", pr.get("mergeable") or "UNKNOWN", head, verdict, len(comments), failed,
                run.get("id") if failed or stalled is not None else None, stalled, owed)


def review_run(repo: Optional[str], head: str, api: Callable[[List[str]], dict] = gh_json,
               clock: Callable[[], float] = time.time) -> Optional[dict]:
    """The review trigger's run that decides whether a review is coming at this exact commit — one still queued or
    running, else one that succeeded, else the latest — as its id, status and conclusion, and for a queued one the
    whole minutes it has waited (`queued_min`); None when it has none."""
    if not head:
        return None
    path = f"repos/{repo or '{owner}/{repo}'}/actions/runs?head_sha={head}&event=pull_request&per_page=50"
    runs = [r for r in ((api(["api", path]) or {}).get("workflow_runs") or []) if r.get("name") == REVIEW_TRIGGER]
    if not runs:
        return None
    running = [r for r in runs if r.get("status") != "completed"]
    succeeded = [r for r in runs if r.get("conclusion") == "success"]
    r = max(running or succeeded or runs, key=lambda r: r.get("created_at") or "")
    out = {"id": r.get("id"), "status": r.get("status"), "conclusion": r.get("conclusion")}
    if r.get("status") == "queued" and r.get("created_at"):
        from datetime import datetime
        made = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")).timestamp()
        out["queued_min"] = max(0, int((clock() - made) // 60))
    return out


def needs_action(s: Snap) -> Optional[str]:
    """The event a pull request in this state already is, with no baseline needed."""
    if s.state == "MERGED":
        return "MERGED"
    if s.state == "CLOSED":
        return "CLOSED"
    if s.mergeable == "CONFLICTING":
        return "CONFLICT"
    if s.verdict == VERDICT_BLOCKING:
        return "BLOCKING"
    if s.verdict is None and s.review_failed:
        return "REVIEW-FAILED"
    if s.verdict is None and s.review_stalled is not None:
        return "REVIEW-STALLED"
    return None


def changed(base: Snap, s: Snap) -> Optional[str]:
    """The event between two polls, or None when nothing the session must act on happened."""
    event = needs_action(s)
    if event:
        return event
    if s.head != base.head:
        return "PUSHED"
    if s.comments > base.comments:
        return "COMMENT"
    return None


def line(event: str, n: int, s: Snap, expect: Optional[str]) -> str:
    run_view = f"`gh run view {s.review_run_id}`" if s.review_run_id else f"`gh run list --commit {s.head}`"
    rerun = f"`gh run rerun {s.review_run_id}`" if s.review_run_id else "`gh run rerun` it"
    owed = (f" — first record the {s.owed} OWED findings of the tip's review, each a row on the board of the project it "
            f"names, as work on the default branch" if s.owed else "")
    do = {"MERGED": f"done{owed} — remove your worktree and local branch",
          "CLOSED": "closed unmerged — find out why before anything else",
          "CONFLICT": "merge the default branch in (keep both sides), push",
          "BLOCKING": "read the review, fix, push",
          "TIP-UNSEEN": f"GitHub still shows tip {s.head[:10]}, not {(expect or '')[:10]}, after {EXPECT_WAIT_POLLS} "
                        f"polls — check your push landed (`git ls-remote origin`), then watch again",
          "REVIEW-FAILED": f"the review trigger's run at the tip ended {s.review_failed}, so no review is coming — "
                           f"read it ({run_view}): GitHub failed to start it ⇒ {rerun}, then watch again · its jobs "
                           f"refused for the account's billing ⇒ you are the CI (DESIGN §5 THE QUEUE BY HAND)",
          "REVIEW-STALLED": f"the review trigger's run at the tip has sat queued {s.review_stalled} min with no job "
                            f"started ({run_view}) — GitHub stalls a run this way and will not cancel it, so no review "
                            f"is coming from it: start a fresh one (`gh pr ready {n} --undo`, then `gh pr ready {n}`), "
                            f"then watch again",
          "COMMENT": "read the new comment",
          "PUSHED": "the tip moved under you — pull it before pushing",
          "TIMEOUT": "still open — check where it stands; watch again only if something is moving",
          "HEAD-MISMATCH": f"merged at {s.head[:10]}, but you expected {(expect or '')[:10]} — carry the rest in a new PR",
          "GH-DOWN": "gh kept failing — check `gh auth status` and the network"}[event]
    return (f"PR #{n} {event}: {do} · state {s.state} · mergeable {s.mergeable} · tip {s.head[:10]} · "
            f"verdict {s.verdict or 'none on tip'} · {s.owed} OWED · {s.comments} comments")


def watch(n: int, fetch: Callable[[], dict], expect: Optional[str] = None, interval: float = 60, max_hours: float = 4,
          max_failures: int = 15, sleep: Callable[[float], None] = time.sleep,
          now: Callable[[], float] = time.monotonic, out: Callable[[str], None] = print) -> int:
    """Poll until an event; print its one line; return its exit code. Never loops past max_hours."""
    def finish(event: str, s: Snap) -> int:
        if event == "MERGED" and expect and not (s.head.startswith(expect) or expect.startswith(s.head)):
            event = "HEAD-MISMATCH"
        out(line(event, n, s, expect))
        return EXIT[event]

    def at_expected(s: Snap) -> bool:
        return not expect or bool(s.head) and (s.head.startswith(expect) or expect.startswith(s.head))

    failures, base, last, first_seen, waited = 0, None, None, None, 0
    deadline = now() + max_hours * 3600
    while True:
        try:
            s = snap_of(fetch())
            failures = 0
        except Exception as e:  # gh down, rate-limited, a bad answer: try again, but not forever
            failures += 1
            if failures >= max_failures:
                out(f"PR #{n} GH-DOWN: {e}")
                return EXIT["GH-DOWN"]
            sleep(interval)
            continue
        last = s
        if base is None and not at_expected(s) and s.state == "OPEN":
            # GitHub still shows a tip before the push: nothing it says is about the push yet
            first_seen = first_seen or s.head
            waited += 1
            event = "PUSHED" if s.head != first_seen else "TIP-UNSEEN" if waited >= EXPECT_WAIT_POLLS else None
            if waited == 1:
                out(f"PR #{n} waiting for tip {(expect or '')[:10]}: GitHub shows {s.head[:10]}")
        else:
            event = needs_action(s) if base is None else changed(base, s)
        if event:
            return finish(event, s)
        if base is None and at_expected(s):
            base = s
            out(f"PR #{n} watching: state {s.state} · mergeable {s.mergeable} · tip {s.head[:10]} · "
                f"verdict {s.verdict or 'none on tip'} · {s.comments} comments")
        if now() >= deadline:
            return finish("TIMEOUT", last)
        sleep(interval)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Watch one pull request; exit the moment it needs you or is done.")
    ap.add_argument("number", type=int)
    ap.add_argument("--repo", default=None, help="owner/name (default: the repository of the current directory)")
    ap.add_argument("--expect-head", default=None, help="the commit you last pushed; MERGED at another tip exits 4")
    ap.add_argument("--interval", type=float, default=60)
    ap.add_argument("--max-hours", type=float, default=4)
    a = ap.parse_args(argv)
    args = ["pr", "view", str(a.number), "--json", "state,mergeable,headRefOid,reviews,comments"]
    if a.repo:
        args += ["--repo", a.repo]

    def fetch() -> dict:
        p = gh_json(args)
        p["reviewRun"] = review_run(a.repo, p.get("headRefOid") or "")
        return p
    return watch(a.number, fetch, a.expect_head, a.interval, a.max_hours)


if __name__ == "__main__":
    sys.exit(main())
