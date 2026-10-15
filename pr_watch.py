#!/usr/bin/env python3
"""THE PR WATCH — what a session runs in the background while the CI takes its pull request to the default branch.

The harness wakes a session only when a background task EXITS; a line a running watch prints is never seen. So this
watch exits — once, with one line saying what to do — the moment the pull request needs the session or is done, and it
always exits:

  MERGED     on the default branch (with --expect-head: at that commit, or exit 4 — carry the rest in a new PR)
  CLOSED     closed without merging
  CONFLICT   GitHub cannot merge it: merge the default branch in, push
  BLOCKING   the reviewer's verdict on the exact tip: fix, push
  COMMENT    a new comment (the queue's conflict or hold notice, a person): read it — a deploy preview's status
             comment is not one: it is posted on every pull request and never asks the session for anything
  PUSHED     the tip moved under the watch: someone else pushed
  TIMEOUT    still waiting after --max-hours: it says where it stands; the session decides whether to watch again
  GH-DOWN    gh failed on every try for --max-failures polls in a row

It checks the pull request BEFORE it waits: a pull request already merged, closed, conflicting or blocked exits at
once — a watch started after the event it waits for never sees a change, and would run until killed. A CLEAN verdict
and a mergeable state that reads UNKNOWN for a poll are not actions: the queue moves a CLEAN pull request, and UNKNOWN
is GitHub still computing.

  python3 pr_watch.py <number> [--repo owner/name] [--expect-head <sha>] [--interval 60] [--max-hours 4]
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

from sweep import VERDICT_BLOCKING, gh_json, verdict_of

# deploy previews post a status comment on every pull request; none of them asks the session for anything
PREVIEW_BOTS = {"cloudflare-workers-and-pages"}

EXIT = {"MERGED": 0, "CLOSED": 0, "CONFLICT": 2, "BLOCKING": 2, "COMMENT": 2, "PUSHED": 2,
        "TIMEOUT": 3, "HEAD-MISMATCH": 4, "GH-DOWN": 5}


@dataclass(frozen=True)
class Snap:
    state: str            # OPEN · MERGED · CLOSED
    mergeable: str        # MERGEABLE · CONFLICTING · UNKNOWN
    head: str
    verdict: Optional[str]
    comments: int


def snap_of(pr: dict) -> Snap:
    """A `gh pr view --json state,mergeable,headRefOid,reviews,comments` answer, reduced to what the watch decides on."""
    head = pr.get("headRefOid") or ""
    verdict = None
    for rv in sorted(pr.get("reviews") or [], key=lambda r: r.get("submittedAt") or ""):
        if ((rv.get("commit") or {}).get("oid") or "") == head:
            verdict = verdict_of(rv.get("body") or "") or verdict
    comments = [c for c in pr.get("comments") or []
                if ((c.get("author") or {}).get("login") or "") not in PREVIEW_BOTS]
    return Snap(pr.get("state") or "", pr.get("mergeable") or "UNKNOWN", head, verdict, len(comments))


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
    do = {"MERGED": "done — remove your worktree and local branch",
          "CLOSED": "closed unmerged — find out why before anything else",
          "CONFLICT": "merge the default branch in (keep both sides), push",
          "BLOCKING": "read the review, fix, push",
          "COMMENT": "read the new comment",
          "PUSHED": "the tip moved under you — pull it before pushing",
          "TIMEOUT": "still open — check where it stands; watch again only if something is moving",
          "HEAD-MISMATCH": f"merged at {s.head[:10]}, but you expected {(expect or '')[:10]} — carry the rest in a new PR",
          "GH-DOWN": "gh kept failing — check `gh auth status` and the network"}[event]
    return (f"PR #{n} {event}: {do} · state {s.state} · mergeable {s.mergeable} · tip {s.head[:10]} · "
            f"verdict {s.verdict or 'none on tip'} · {s.comments} comments")


def watch(n: int, fetch: Callable[[], dict], expect: Optional[str] = None, interval: float = 60, max_hours: float = 4,
          max_failures: int = 15, sleep: Callable[[float], None] = time.sleep,
          now: Callable[[], float] = time.monotonic, out: Callable[[str], None] = print) -> int:
    """Poll until an event; print its one line; return its exit code. Never loops past max_hours."""
    def finish(event: str, s: Snap) -> int:
        if event == "MERGED" and expect and not (s.head.startswith(expect) or expect.startswith(s.head)):
            event = "HEAD-MISMATCH"
        out(line(event, n, s, expect))
        return EXIT[event]

    failures, base, last = 0, None, None
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
        event = needs_action(s) if base is None else changed(base, s)
        if event:
            return finish(event, s)
        if base is None:
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
    return watch(a.number, lambda: gh_json(args), a.expect_head, a.interval, a.max_hours)


if __name__ == "__main__":
    sys.exit(main())
