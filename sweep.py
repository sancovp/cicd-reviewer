#!/usr/bin/env python3
"""THE SWEEP — no branch is left unmerged. Deterministic: git's API only, never a model.

Runs on a schedule in the reviewer's own (public, free-minutes) repo, over every repository the owner has (its own
sources, not forks, not archived). For every branch that is not the default branch and not a STANDING branch
(`om-is-the-base`, the one branch kept beside the default):

  - its tip is already in the default branch, or a MERGED pull request has exactly that tip ⇒ the work is on the
    default branch: the branch is deleted.
  - it has an OPEN pull request ⇒ when the reviewer's last verdict on that exact tip is CLEAN and the request has no
    conflict, it is merged (squash) and the branch deleted; with a conflict, it is listed STUCK; with no verdict on
    that tip, a review is dispatched (and `review.yml` merges it when the verdict is CLEAN).
  - it has no open pull request ⇒ one is opened (title: the branch, body: its commits) and a review dispatched.

What it cannot move is listed in ONE tracking issue on the canonical home (`UNMERGED WORK`), rewritten every run.
It never force-pushes, never touches a default or standing branch, deletes only a branch whose exact tip is on the
default branch, and dispatches at most `--max-reviews` reviews a run (each costs a model run).

  python3 sweep.py --owner sancovp [--repo owner/name ...] [--dry-run] [--max-reviews 20]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

STANDING = {"om-is-the-base"}
TRACKING_REPO = "sancovp/sanctuary-revolution-alpha"
TRACKING_TITLE = "UNMERGED WORK"
VERDICT_CLEAN = "VERDICT: CLEAN"
VERDICT_BLOCKING = "VERDICT: BLOCKING"


def gh(args: List[str], input_text: Optional[str] = None) -> str:
    """One `gh` call; its stdout. A failure raises with gh's own message."""
    r = subprocess.run(["gh", *args], input=input_text, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}…: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


def gh_json(args: List[str]):
    out = gh(args)
    return json.loads(out) if out.strip() else None


def gh_lines(args: List[str]) -> List[dict]:
    """A paged `gh api … --paginate --jq '.[]'`: one JSON object per line, every page."""
    return [json.loads(line) for line in gh(args).splitlines() if line.strip()]


def verdict_of(body: str) -> Optional[str]:
    """The verdict line a review ends with, or None when it has none."""
    for line in reversed((body or "").strip().splitlines()):
        line = line.strip()
        if line in (VERDICT_CLEAN, VERDICT_BLOCKING):
            return line
        if line:
            return None
    return None


def last_verdict(reviews: List[dict], head_sha: str) -> Optional[str]:
    """The newest verdict a review gave on exactly this tip; a verdict on an older tip does not count."""
    for rv in sorted(reviews, key=lambda r: r.get("submitted_at") or "", reverse=True):
        if rv.get("commit_id") == head_sha:
            v = verdict_of(rv.get("body") or "")
            if v:
                return v
    return None


@dataclass
class Branch:
    name: str
    sha: str


@dataclass
class Plan:
    """What the sweep decided for one branch."""
    repo: str
    branch: str
    action: str            # delete · merge · review · open · stuck · keep
    why: str
    pr: Optional[int] = None


@dataclass
class Facts:
    """Everything decide() needs about one branch, read beforehand — so decide() is pure."""
    repo: str
    default: str
    branch: Branch
    in_default: bool                       # its tip is an ancestor of the default branch
    merged_pr_tips: List[str] = field(default_factory=list)
    open_pr: Optional[dict] = None         # {number, mergeable, head_sha}
    verdict: Optional[str] = None          # the last verdict on the open PR's tip
    publish_source: Optional[str] = None   # this repo is a PUBLISH TARGET of that subdir of the canonical home


def decide(f: Facts) -> Plan:
    b = f.branch
    if b.name == f.default or b.name in STANDING:
        return Plan(f.repo, b.name, "keep", "the default or a standing branch")
    if f.in_default:
        return Plan(f.repo, b.name, "delete", "its tip is already on the default branch")
    if b.sha in f.merged_pr_tips:
        return Plan(f.repo, b.name, "delete", "a merged pull request has exactly this tip")
    if f.publish_source:
        n = f.open_pr["number"] if f.open_pr else None
        return Plan(f.repo, b.name, "stuck", f"a publish target: the next publish overwrites a merge here — port the "
                    f"work into `{f.publish_source}` of the canonical home", n)
    if f.open_pr:
        n = f.open_pr["number"]
        if f.open_pr.get("mergeable") == "CONFLICTING":
            return Plan(f.repo, b.name, "stuck", "conflicts with the default branch", n)
        if f.verdict == VERDICT_CLEAN and f.open_pr.get("mergeable") == "MERGEABLE":
            return Plan(f.repo, b.name, "merge", "the reviewer's verdict on this tip is CLEAN", n)
        if f.verdict == VERDICT_BLOCKING:
            return Plan(f.repo, b.name, "stuck", "the reviewer's verdict is BLOCKING — fix and push", n)
        return Plan(f.repo, b.name, "review", "no verdict yet on this tip", n)
    return Plan(f.repo, b.name, "open", "no pull request")


# ── reading the facts (gh) ──────────────────────────────────────────────────────────────────────

def repos_of(owner: str) -> List[dict]:
    return gh_json(["repo", "list", owner, "--limit", "1000", "--source", "--no-archived",
                    "--json", "nameWithOwner,defaultBranchRef"]) or []


def branches_of(repo: str) -> List[Branch]:
    rows = gh_lines(["api", f"repos/{repo}/branches", "--paginate", "--jq", ".[] | {name, sha: .commit.sha}"])
    return [Branch(r["name"], r["sha"]) for r in rows]


def publish_targets() -> Dict[str, str]:
    """public repo → its source subdir in the canonical home, from the publishing manifest (a merge into a target is
    overwritten by the next publish, so a target's unmerged work belongs in the canonical home instead)."""
    import base64
    try:
        raw = gh(["api", f"repos/{TRACKING_REPO}/contents/scalable-publishing/publish-manifest.json", "--jq", ".content"])
        m = json.loads(base64.b64decode(raw))
    except (RuntimeError, ValueError) as e:
        raise RuntimeError(f"the publishing manifest is unreadable, so publish targets cannot be told apart: {e}")
    units = m if isinstance(m, list) else m.get("units", m)
    return {u["public_repo"]: u["subdir"] for u in units if u.get("public_repo")}


COMPARE = ("query($o:String!,$n:String!,$b:String!,$h:String!){repository(owner:$o,name:$n){"
           "ref(qualifiedName:$b){compare(headRef:$h){aheadBy}}}}")


def ahead_by(repo: str, default: str, branch: str) -> int:
    """How many commits the branch has that the default branch lacks. GraphQL's comparison counts without building
    the diff — REST's compare answers 500 on a large one, which left those branches unread."""
    owner, name = repo.split("/", 1)
    out = gh_json(["api", "graphql", "-f", f"query={COMPARE}", "-f", f"o={owner}", "-f", f"n={name}",
                   "-f", f"b=refs/heads/{default}", "-f", f"h=refs/heads/{branch}"])
    cmp = (((out or {}).get("data") or {}).get("repository") or {}).get("ref") or {}
    if not cmp.get("compare"):
        raise RuntimeError(f"no comparison for {branch} against {default}")
    return int(cmp["compare"]["aheadBy"])


def gather(repo: str, default: str, b: Branch, publish_source: Optional[str] = None) -> Facts:
    in_default = ahead_by(repo, default, b.name) == 0
    prs = gh_json(["pr", "list", "--repo", repo, "--head", b.name, "--state", "all", "--limit", "50",
                   "--json", "number,state,headRefOid,mergeable"]) or []
    merged_tips = [p["headRefOid"] for p in prs if p["state"] == "MERGED"]
    open_pr = next(({"number": p["number"], "mergeable": p["mergeable"], "head_sha": p["headRefOid"]}
                    for p in prs if p["state"] == "OPEN"), None)
    verdict = None
    if open_pr:
        reviews = gh_lines(["api", f"repos/{repo}/pulls/{open_pr['number']}/reviews", "--paginate", "--jq",
                            ".[] | {commit_id, submitted_at, body}"])
        verdict = last_verdict(reviews, open_pr["head_sha"])
    return Facts(repo, default, b, in_default, merged_tips, open_pr, verdict, publish_source)


# ── acting ──────────────────────────────────────────────────────────────────────────────────────

def act(p: Plan, default: str, b: Branch, owner: str, dry: bool, log: Callable[[str], None]) -> Plan:
    if dry or p.action in ("keep", "stuck"):
        return p
    try:
        if p.action == "delete":
            gh(["api", "-X", "DELETE", f"repos/{p.repo}/git/refs/heads/{b.name}"])
        elif p.action == "merge":
            gh(["pr", "merge", str(p.pr), "--repo", p.repo, "--squash", "--delete-branch",
                "--match-head-commit", b.sha])
        elif p.action in ("open", "review"):
            if p.action == "open":
                n = ahead_by(p.repo, default, b.name)
                url = gh(["pr", "create", "--repo", p.repo, "--head", b.name, "--base", default,
                          "--title", b.name, "--body",
                          f"Opened by the sweep: this branch has {n} commit(s) not on `{default}` and had no pull "
                          "request. The reviewer reviews it; a CLEAN verdict on its tip with no conflict merges it."
                          ]).strip()
                p.pr = int(url.rstrip("/").split("/")[-1])
            payload = json.dumps({"event_type": "review-pr", "client_payload": {
                "repo": p.repo, "pr_number": str(p.pr), "base_ref": default, "head_ref": b.name}})
            gh(["api", "-X", "POST", f"repos/{owner}/cicd-reviewer/dispatches", "--input", "-"], payload)
    except RuntimeError as e:
        log(f"  ⚠ {p.repo} {b.name}: {p.action} failed — {e}")
        return Plan(p.repo, p.branch, "stuck", f"{p.action} failed: {e}", p.pr)
    return p


def merge_pr(repo: str, pr: int, log: Callable[[str], None], wait: Callable[[float], None] = None) -> str:
    """After a review: merge this pull request when the verdict on its exact tip is CLEAN and it has no conflict.
    Returns what happened: merged · conflict · blocking · no-verdict · not-open · unknown."""
    import time
    wait = wait or time.sleep
    view = None
    for _ in range(10):                      # GitHub computes mergeability after a push; UNKNOWN until it has
        view = gh_json(["pr", "view", str(pr), "--repo", repo, "--json", "state,mergeable,headRefOid,baseRefName"])
        if view["state"] != "OPEN" or view["mergeable"] != "UNKNOWN":
            break
        wait(6)
    if view["state"] != "OPEN":
        log(f"#{pr} is {view['state']} — nothing to merge")
        return "not-open"
    reviews = gh_lines(["api", f"repos/{repo}/pulls/{pr}/reviews", "--paginate", "--jq",
                        ".[] | {commit_id, submitted_at, body}"])
    verdict = last_verdict(reviews, view["headRefOid"])
    if view["mergeable"] == "CONFLICTING":
        comments = gh(["api", f"repos/{repo}/issues/{pr}/comments", "--paginate", "--jq", ".[].body"])
        marker = f"conflicts with `{view['baseRefName']}` at {view['headRefOid'][:12]}"
        if marker not in comments:
            gh(["pr", "comment", str(pr), "--repo", repo, "--body",
                f"This pull request {marker}. The session working on it merges `{view['baseRefName']}` in and "
                "resolves every conflict keeping both sides' work, then pushes (never a force push); the reviewer "
                "reviews the new tip and merges it on a CLEAN verdict."])
        log(f"#{pr} conflicts — commented")
        return "conflict"
    if verdict == VERDICT_BLOCKING:
        log(f"#{pr} verdict BLOCKING — left for the session to fix")
        return "blocking"
    if verdict != VERDICT_CLEAN:
        log(f"#{pr} has no verdict on its tip {view['headRefOid'][:12]} — not merged")
        return "no-verdict"
    if view["mergeable"] != "MERGEABLE":
        log(f"#{pr} mergeability still {view['mergeable']} — not merged; the sweep tries again")
        return "unknown"
    gh(["pr", "merge", str(pr), "--repo", repo, "--squash", "--delete-branch",
        "--match-head-commit", view["headRefOid"]])
    log(f"#{pr} merged (verdict CLEAN on {view['headRefOid'][:12]})")
    return "merged"


def tracking_body(plans: List[Plan]) -> str:
    stuck = [p for p in plans if p.action == "stuck"]
    lines = ["Rewritten by the sweep (`automation/cicd-reviewer/sweep.py`) on every run. Each row is work on a branch "
             "that is not on its default branch and that the sweep could not move. The session working in that "
             "repo resolves it: a conflict by merging the default branch in and resolving (both sides' work kept), "
             "a BLOCKING verdict by fixing and pushing — then the reviewer merges it.", ""]
    if not stuck:
        lines.append("Nothing stuck. ✅")
    else:
        lines += ["| repo | branch | pull request | why |", "|---|---|---|---|"]
        for p in sorted(stuck, key=lambda x: (x.repo, x.branch)):
            pr = f"#{p.pr}" if p.pr else "—"
            lines.append(f"| {p.repo} | `{p.branch}` | {pr} | {p.why} |")
    return "\n".join(lines) + "\n"


def write_tracking(plans: List[Plan], dry: bool, log: Callable[[str], None]) -> None:
    body = tracking_body(plans)
    if dry:
        log("\n--- the tracking issue would read ---\n" + body)
        return
    found = gh_json(["issue", "list", "--repo", TRACKING_REPO, "--state", "open", "--search",
                     f"in:title \"{TRACKING_TITLE}\"", "--json", "number,title"]) or []
    num = next((i["number"] for i in found if i["title"] == TRACKING_TITLE), None)
    if num:
        gh(["issue", "edit", str(num), "--repo", TRACKING_REPO, "--body", body])
    else:
        gh(["issue", "create", "--repo", TRACKING_REPO, "--title", TRACKING_TITLE, "--body", body])


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--owner", required=True)
    ap.add_argument("--repo", action="append", help="only these repos (owner/name); default: every source repo")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-reviews", type=int, default=20)
    ap.add_argument("--merge-pr", type=int, help="only: merge this pull request of the one --repo if its verdict is CLEAN")
    a = ap.parse_args(argv)
    log = print
    if a.merge_pr:
        if not a.repo or len(a.repo) != 1:
            ap.error("--merge-pr needs exactly one --repo")
        merge_pr(a.repo[0], a.merge_pr, log)
        return 0

    targets = publish_targets()
    repos = repos_of(a.owner)
    if a.repo:
        repos = [r for r in repos if r["nameWithOwner"] in set(a.repo)]
    plans: List[Plan] = []
    reviews_left = a.max_reviews
    for r in repos:
        repo = r["nameWithOwner"]
        default = (r.get("defaultBranchRef") or {}).get("name")
        if not default:
            continue
        try:
            branches = branches_of(repo)
        except RuntimeError as e:
            log(f"⚠ {repo}: branches unreadable — {e}")
            continue
        for b in branches:
            if b.name == default or b.name in STANDING:
                continue
            try:
                p = decide(gather(repo, default, b, targets.get(repo)))
            except RuntimeError as e:
                p = Plan(repo, b.name, "keep", f"could not be read this run, tried again next run: {str(e)[:120]}")
            if p.action in ("open", "review"):
                if reviews_left <= 0:
                    p = Plan(repo, b.name, "keep", f"{p.action} deferred to the next run (review budget spent)", p.pr)
                else:
                    reviews_left -= 1
            p = act(p, default, b, a.owner, a.dry_run, log)
            plans.append(p)
            log(f"{p.action:7} {repo} {b.name}{' #' + str(p.pr) if p.pr else ''} — {p.why}")
    write_tracking(plans, a.dry_run, log)
    counts: Dict[str, int] = {}
    for p in plans:
        counts[p.action] = counts.get(p.action, 0) + 1
    log("\nsummary: " + (", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "no branches"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
