#!/usr/bin/env python3
"""WHEN THE REVIEWER'S MODEL IS DOWN — merges never wait on it (DESIGN.md §2 · §4). Deterministic: no model call but
the one-token question that asks whether the model answers.

  python3 outage.py probe                                  prints up · down <code> · broken <code>   (exit 0 · 10 · 1)
  python3 outage.py mark-unreviewed <repo> <pr> <code>     the UNREVIEWED verdict on the pull request's tip
  python3 outage.py close-late <repo> <pr> <since>         after a late review: BLOCKING opens a "Fix owed" issue; the
                                                           `review-owed` label comes off (exit 1 when no verdict landed)

DOWN is what the model's own answer says: 429 (the plan spent, or a burst), a 5xx, no answer at all (0), or a key it
refuses (401 · 403) — asked three times a minute apart, so a passing burst is not an outage. Any other answer (a 400 for
a model name it does not know) is BROKEN: the run fails loudly and nothing is marked, since a wrong setting is not an
outage and must not let every pull request through unread.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Callable, List, Optional, Tuple

from sweep import REVIEW_OWED, VERDICT_BLOCKING, VERDICT_CLEAN, VERDICT_UNREVIEWED, gh, gh_json, gh_lines, verdict_of

ENDPOINT = "https://api.minimax.io/anthropic/v1/messages"
TRIES, APART = 3, 60


def classify(code: int) -> str:
    if code == 200:
        return "up"
    if code in (0, 401, 403, 408, 429) or 500 <= code < 600:
        return "down"
    return "broken"


def ask(key: str, model: str) -> int:
    """one one-token message; the HTTP status (0 when nothing answered)"""
    body = json.dumps({"model": model, "max_tokens": 1, "messages": [{"role": "user", "content": "ping"}]}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
        "content-type": "application/json", "anthropic-version": "2023-06-01", "x-api-key": key,
        "authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0


def probe(key: str, model: str, asker: Callable[[str, str], int] = ask,
          sleep: Callable[[float], None] = time.sleep, tries: int = TRIES, apart: float = APART) -> Tuple[str, int]:
    code = 0
    for i in range(tries):
        code = asker(key, model)
        state = classify(code)
        if state != "down":
            return state, code
        if i < tries - 1:
            sleep(apart)
    return "down", code


def unreviewed_body(code: int) -> str:
    return (f"The reviewer's model did not answer (HTTP {code}, asked {TRIES} times a minute apart), so this tip was not "
            "reviewed. The merge queue merges it once its automatic checks pass and labels it `review-owed`; the "
            "reviewer reads it after it merges, and a defect it finds opens a \"Fix owed\" issue "
            f"(automation/cicd-reviewer/DESIGN.md §2).\n\n{VERDICT_UNREVIEWED}")


def mark_unreviewed(repo: str, pr: str, code: int) -> None:
    gh(["pr", "review", str(pr), "--repo", repo, "--comment", "--body", unreviewed_body(code)])


def late_verdict(comments: List[dict], since: str) -> Optional[str]:
    """the newest CLEAN or BLOCKING verdict among the comments posted since the late review began"""
    for c in sorted(comments, key=lambda c: c.get("created_at") or "", reverse=True):
        if (c.get("created_at") or "") < since:
            break
        v = verdict_of(c.get("body") or "")
        if v in (VERDICT_CLEAN, VERDICT_BLOCKING):
            return v
    return None


def close_late(repo: str, pr: str, since: str, log: Callable[[str], None] = print) -> int:
    comments = gh_lines(["api", f"repos/{repo}/issues/{pr}/comments", "--paginate", "--jq", ".[] | {created_at, body}"])
    v = late_verdict(comments, since)
    if v is None:
        log(f"#{pr}: the late review posted no verdict — the label stays and the next sweep sends it again")
        return 1
    if v == VERDICT_BLOCKING:
        info = gh_json(["pr", "view", str(pr), "--repo", repo, "--json", "title,url"]) or {}
        gh(["issue", "create", "--repo", repo, "--title", f"Fix owed: #{pr} {info.get('title', '')}".strip(), "--body",
            f"#{pr} merged while the reviewer's model was down. Its review, run after it merged, found a defect: "
            f"{info.get('url', '')}. The session working in this repository fixes it on a new branch and hands it off "
            "as a ready pull request."])
        log(f"#{pr}: BLOCKING after the merge — a Fix owed issue is open")
    gh(["pr", "edit", str(pr), "--repo", repo, "--remove-label", REVIEW_OWED])
    log(f"#{pr}: late review {v}; {REVIEW_OWED} removed")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    a = argv if argv is not None else sys.argv[1:]
    if not a:
        print(__doc__)
        return 2
    if a[0] == "probe":
        state, code = probe(os.environ.get("MINIMAX_API_KEY", ""), os.environ.get("CICD_MODEL", "MiniMax-M3"))
        print(state if state == "up" else f"{state} {code}")
        return {"up": 0, "down": 10, "broken": 1}[state]
    if a[0] == "mark-unreviewed" and len(a) == 4:
        mark_unreviewed(a[1], a[2], int(a[3]))
        return 0
    if a[0] == "close-late" and len(a) == 4:
        return close_late(a[1], a[2], a[3])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
