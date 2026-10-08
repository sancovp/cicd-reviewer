#!/usr/bin/env python3
"""THE MERGE QUEUE — one merge at a time per repo, and a verdict counts only on the main it was given against.

Reviews run in parallel (they only read). MERGING runs here, one queue per repo (the workflow's concurrency group),
deterministically, with the model called in exactly one place — when ready pull requests overlap:

  1. READY = an open pull request into the default branch whose reviewer's verdict on its EXACT tip is CLEAN, that
     GitHub calls MERGEABLE, and that the coordinator has not held at this tip.
  2. FRESH = no commit has landed on the default branch, since that verdict was posted, touching any file the pull
     request touches. A verdict that is not fresh was given about a main that no longer exists: the pull request is
     reviewed again (dispatched, spaced) and waits.
  3. Ready-and-fresh pull requests are grouped by the files they share. A group of one merges. A group of several
     goes to the COORDINATOR (the reviewer in MODE=coordinate), which reads their diffs and answers the order to
     merge them in and which to HOLD because they contradict another or would break together. The first in its order
     merges; the rest of the group now overlap a fresh merge, so each is reviewed again against the new main.
  4. A CONFLICTING pull request gets one comment saying so (the session resolves it); a held one gets one comment
     with the coordinator's reason, and is skipped until its tip changes.

Every merge is a squash at the exact reviewed tip (`--match-head-commit`), the branch deleted. Never a force push.

  python3 merge_queue.py --repo owner/name [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set

from sweep import STANDING, VERDICT_BLOCKING, VERDICT_CLEAN, _space_out, gh, gh_json, gh_lines, verdict_of

HELD = "held by the merge coordinator at"
CONFLICT = "conflicts with"
COMMIT_CAP = 100          # more commits than this since a verdict ⇒ treated as not fresh (re-reviewed)


@dataclass
class PR:
    number: int
    title: str
    head: str
    branch: str
    created: str
    mergeable: str
    files: Set[str] = field(default_factory=set)
    verdict: Optional[str] = None
    verdict_at: Optional[str] = None
    comments: str = ""


# ── the pure decisions ─────────────────────────────────────────────────────────────────────────

def verdict_on_tip(reviews: List[dict], head: str):
    """(verdict, posted_at) of the newest review on exactly this tip that ends in a verdict line."""
    for rv in sorted(reviews, key=lambda r: r.get("submitted_at") or "", reverse=True):
        if rv.get("commit_id") == head:
            v = verdict_of(rv.get("body") or "")
            if v:
                return v, rv.get("submitted_at")
    return None, None


def held_at_tip(p: PR) -> bool:
    return f"{HELD} {p.head[:12]}" in p.comments


def fresh(p: PR, changed: Optional[Set[str]]) -> bool:
    """None = too much landed to tell ⇒ not fresh."""
    return changed is not None and not (p.files & changed)


def groups(prs: List[PR]) -> List[List[PR]]:
    """Connected components of 'shares a file', each ordered oldest first, the groups oldest first."""
    left = sorted(prs, key=lambda p: p.created)
    out: List[List[PR]] = []
    while left:
        g = [left.pop(0)]
        files = set(g[0].files)
        grew = True
        while grew:
            grew = False
            for p in list(left):
                if p.files & files:
                    g.append(p)
                    files |= p.files
                    left.remove(p)
                    grew = True
        out.append(sorted(g, key=lambda p: p.created))
    return out


def apply_decision(group: List[PR], decision: Optional[dict]):
    """(first to merge or None, [(pr, reason) held], [prs to re-review]). A missing or broken decision falls back to
    oldest first, nothing held: the queue never stalls on the coordinator."""
    by_num = {p.number: p for p in group}
    holds = []
    order: List[int] = []
    if isinstance(decision, dict):
        for h in decision.get("hold") or []:
            try:
                n = int(h.get("pr"))
            except (TypeError, ValueError, AttributeError):
                continue
            if n in by_num:
                holds.append((by_num[n], str(h.get("reason") or "no reason given")))
        for n in decision.get("order") or []:
            try:
                n = int(n)
            except (TypeError, ValueError):
                continue
            if n in by_num and n not in order:
                order.append(n)
    held = {p.number for p, _ in holds}
    order = [n for n in order if n not in held] + [p.number for p in group if p.number not in order and p.number not in held]
    first = by_num[order[0]] if order else None
    rereview = [by_num[n] for n in order[1:]]
    return first, holds, rereview


# ── reading (gh) ───────────────────────────────────────────────────────────────────────────────

def open_prs(repo: str, base: str) -> List[PR]:
    rows = gh_json(["pr", "list", "--repo", repo, "--state", "open", "--base", base, "--limit", "100", "--json",
                    "number,title,headRefOid,headRefName,createdAt,mergeable,files"]) or []
    prs = []
    for r in rows:
        p = PR(r["number"], r["title"], r["headRefOid"], r["headRefName"], r["createdAt"], r["mergeable"],
               {f["path"] for f in (r.get("files") or [])})
        reviews = gh_lines(["api", f"repos/{repo}/pulls/{p.number}/reviews", "--paginate", "--jq",
                            ".[] | {commit_id, submitted_at, body}"])
        p.verdict, p.verdict_at = verdict_on_tip(reviews, p.head)
        p.comments = gh(["api", f"repos/{repo}/issues/{p.number}/comments", "--paginate", "--jq", ".[].body"])
        prs.append(p)
    return prs


def changed_since(repo: str, base: str, since: str) -> Optional[Set[str]]:
    shas = gh_lines(["api", f"repos/{repo}/commits?sha={base}&since={since}&per_page={COMMIT_CAP}", "--jq", ".[].sha"])
    if len(shas) >= COMMIT_CAP:
        return None
    files: Set[str] = set()
    for sha in shas:
        files |= set(gh_lines(["api", f"repos/{repo}/commits/{sha}", "--jq", ".files[].filename"]))
    return files


# ── the coordinator (the one model call) ───────────────────────────────────────────────────────

def coordinate_with_reviewer(repo: str, group: List[PR], log: Callable[[str], None]) -> Optional[dict]:
    """Run the reviewer image in MODE=coordinate over this group; its answer is the JSON it writes to /out."""
    owner = repo.split("/")[0]
    out = tempfile.mkdtemp()
    os.chmod(out, 0o777)
    payload = json.dumps([{"number": p.number, "title": p.title, "files": sorted(p.files)} for p in group])
    cmd = ["docker", "run", "--rm", "-e", "MODE=coordinate", "-e", "MINIMAX_API_KEY", "-e", f"GITHUB_TOKEN={os.environ.get('GH_TOKEN', '')}",
           "-e", f"GITHUB_REPOSITORY={repo}", "-e", f"COORD_INPUT={payload}", "-v", f"{out}:/out",
           f"ghcr.io/{owner}/cicd-reviewer:latest"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    log(f"  coordinator exit {r.returncode}")
    try:
        with open(os.path.join(out, "decision.json")) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        log(f"  coordinator gave no decision ({e}) — oldest first, nothing held")
        return None


# ── acting ─────────────────────────────────────────────────────────────────────────────────────

def dispatch_review(repo: str, p: PR, base: str, wait, now) -> None:
    _space_out(wait, now)
    owner = repo.split("/")[0]
    gh(["api", "-X", "POST", f"repos/{owner}/cicd-reviewer/dispatches", "--input", "-"], json.dumps({
        "event_type": "review-pr", "client_payload": {"repo": repo, "pr_number": str(p.number),
                                                      "base_ref": base, "head_ref": p.branch}}))


def comment_once(repo: str, p: PR, marker: str, body: str, dry: bool) -> None:
    if marker in p.comments or dry:
        return
    gh(["pr", "comment", str(p.number), "--repo", repo, "--body", body])


def run(repo: str, dry: bool = False, log: Callable[[str], None] = print,
        coordinate: Callable = None, wait: Callable[[float], None] = None, now: Callable[[], float] = None) -> Dict[str, list]:
    import time
    wait, now = wait or time.sleep, now or time.time
    coordinate = coordinate or coordinate_with_reviewer
    base = gh_json(["repo", "view", repo, "--json", "defaultBranchRef"])["defaultBranchRef"]["name"]
    report: Dict[str, list] = {"merged": [], "rereview": [], "held": [], "conflict": [], "waiting": []}
    ready: List[PR] = []
    for p in open_prs(repo, base):
        if p.branch in STANDING:               # the standing branch is never queued, commented on or merged
            continue
        if p.mergeable == "CONFLICTING":
            marker = f"{CONFLICT} `{base}` at {p.head[:12]}"
            comment_once(repo, p, marker, f"This pull request {marker}. The session working on it merges `{base}` in "
                         "and resolves every conflict keeping both sides' work, then pushes (never a force push); the "
                         "reviewer reviews the new tip and the merge queue merges it.", dry)
            report["conflict"].append(p.number)
            continue
        if p.verdict != VERDICT_CLEAN or p.mergeable != "MERGEABLE" or held_at_tip(p):
            report["waiting"].append(p.number)
            continue
        if not fresh(p, changed_since(repo, base, p.verdict_at)):
            log(f"#{p.number}: its CLEAN verdict predates a change to its files on {base} — reviewed again")
            if not dry:
                dispatch_review(repo, p, base, wait, now)
            report["rereview"].append(p.number)
            continue
        ready.append(p)
    for g in groups(ready):
        decision = coordinate(repo, g, log) if len(g) > 1 else None
        first, holds, rereview = apply_decision(g, decision)
        for p, reason in holds:
            marker = f"{HELD} {p.head[:12]}"
            comment_once(repo, p, marker, f"This pull request is {marker}: {reason}", dry)
            report["held"].append(p.number)
            log(f"#{p.number} held — {reason}")
        if first:
            log(f"#{first.number} merges" + (f" (first of {[p.number for p in g]})" if len(g) > 1 else ""))
            if not dry:
                try:
                    gh(["pr", "merge", str(first.number), "--repo", repo, "--squash", "--delete-branch",
                        "--match-head-commit", first.head])
                except RuntimeError as e:
                    log(f"#{first.number} did not merge — {e}")
                    report["waiting"].append(first.number)
                    first = None
            if first:
                report["merged"].append(first.number)
        for p in rereview:
            log(f"#{p.number} overlaps what just merged — reviewed again against the new {base}")
            if not dry:
                dispatch_review(repo, p, base, wait, now)
            report["rereview"].append(p.number)
    done = ", ".join(f"{k} {v}" for k, v in report.items() if v)
    log("queue: " + (done or "nothing to do"))
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--coordinate", help="only: ask the coordinator about these open pull requests (e.g. 12,15), "
                                         "print its decision, act on nothing")
    a = ap.parse_args(argv)
    if a.coordinate:
        base = gh_json(["repo", "view", a.repo, "--json", "defaultBranchRef"])["defaultBranchRef"]["name"]
        want = {int(n) for n in a.coordinate.split(",") if n.strip()}
        group = [p for p in open_prs(a.repo, base) if p.number in want]
        decision = coordinate_with_reviewer(a.repo, group, print)
        print("decision:", json.dumps(decision))
        first, holds, rereview = apply_decision(group, decision)
        print("would merge first:", first.number if first else None, "· hold:", [(p.number, r) for p, r in holds],
              "· re-review:", [p.number for p in rereview])
        return 0
    run(a.repo, a.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
