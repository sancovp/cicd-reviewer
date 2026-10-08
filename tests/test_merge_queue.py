#!/usr/bin/env python3
"""Tests for merge_queue.py — pure decisions, then run() against a fake GitHub. No network.
Run: python3 tests/test_merge_queue.py"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
for name in ("sweep", "merge_queue"):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
import sweep  # noqa: E402
import merge_queue as mq  # noqa: E402

PR = mq.PR


def pr(n, files, created="2026-01-0%d", head=None, **kw):
    return PR(n, f"pr {n}", head or f"sha{n}", f"b{n}", created % n if "%d" in created else created, kw.get("mergeable", "MERGEABLE"),
              set(files), kw.get("verdict", sweep.VERDICT_CLEAN), kw.get("verdict_at", "2026-01-10T00:00:00Z"), kw.get("comments", ""))


def t_groups_join_prs_that_share_a_file_transitively():
    g = mq.groups([pr(1, {"a"}), pr(2, {"b"}), pr(3, {"a", "c"}), pr(4, {"c"})])
    assert [[p.number for p in x] for x in g] == [[1, 3, 4], [2]]


def t_fresh_only_when_nothing_touched_its_files():
    p = pr(1, {"a", "b"})
    assert mq.fresh(p, set()) and mq.fresh(p, {"z"})
    assert not mq.fresh(p, {"b"})
    assert not mq.fresh(p, None)          # too much landed to tell


def t_decision_order_and_holds():
    g = [pr(1, {"a"}), pr(2, {"a"}), pr(3, {"a"})]
    first, holds, rere = mq.apply_decision(g, {"order": [3, 1, 2], "hold": [{"pr": 1, "reason": "contradicts #3"}]})
    assert first.number == 3 and [p.number for p, _ in holds] == [1] and [p.number for p in rere] == [2]


def t_a_broken_decision_falls_back_to_oldest_first_nothing_held():
    g = [pr(1, {"a"}), pr(2, {"a"})]
    for bad in (None, "nonsense", {"order": ["x"], "hold": [{"pr": "y"}]}, {"order": [99]}):
        first, holds, rere = mq.apply_decision(g, bad)
        assert first.number == 1 and holds == [] and [p.number for p in rere] == [2], bad


def t_holding_everyone_merges_no_one():
    g = [pr(1, {"a"}), pr(2, {"a"})]
    first, holds, rere = mq.apply_decision(g, {"hold": [{"pr": 1, "reason": "x"}, {"pr": 2, "reason": "y"}]})
    assert first is None and len(holds) == 2 and rere == []


def t_verdict_on_tip_carries_its_time_and_ignores_older_tips():
    reviews = [{"commit_id": "t", "submitted_at": "2", "body": "VERDICT: CLEAN"},
               {"commit_id": "old", "submitted_at": "3", "body": "VERDICT: CLEAN"}]
    assert mq.verdict_on_tip(reviews, "t") == (sweep.VERDICT_CLEAN, "2")
    assert mq.verdict_on_tip(reviews, "new") == (None, None)


def t_held_only_at_the_held_tip():
    p = pr(1, {"a"}, head="abcdef1234567890", comments="This pull request is held by the merge coordinator at abcdef123456: x")
    assert mq.held_at_tip(p)
    p.head = "ffff00001111"
    assert not mq.held_at_tip(p)


def t_reviews_are_dispatched_one_spacing_apart():
    waits, clock = [], [1000.0]
    sweep._last_dispatch[0] = 0.0
    step = lambda s: (waits.append(s), clock.__setitem__(0, clock[0] + s))
    sweep._space_out(step, lambda: clock[0])
    clock[0] += 10
    sweep._space_out(step, lambda: clock[0])
    assert waits == [sweep.REVIEW_SPACING - 10], waits


# ── run() against a fake GitHub ───────────────────────────────────────────────────────────────

def fake_github(prs, changed_files_by_sha=None, commits_since=None):
    """prs: list of dicts as `gh pr list --json` returns them plus 'reviews' and 'comments'."""
    calls = []

    def gh(args, input_text=None):
        calls.append((args, input_text))
        a = " ".join(args)
        if a.startswith("repo view"):
            return json.dumps({"defaultBranchRef": {"name": "main"}})
        if a.startswith("pr list"):
            return json.dumps([{k: v for k, v in p.items() if k not in ("reviews", "comments")} for p in prs])
        for p in prs:
            if a.startswith(f"api repos/o/r/pulls/{p['number']}/reviews"):
                return "\n".join(json.dumps(r) for r in p["reviews"])
            if a.startswith(f"api repos/o/r/issues/{p['number']}/comments"):
                return p.get("comments", "")
        if a.startswith("api repos/o/r/commits?"):
            return "\n".join(json.dumps(s) for s in (commits_since or []))
        if a.startswith("api repos/o/r/commits/"):
            sha = args[1].rsplit("/", 1)[1]
            return "\n".join(json.dumps(f) for f in (changed_files_by_sha or {}).get(sha, []))
        return ""
    return gh, calls


def ghpr(n, files, head=None, created=None, mergeable="MERGEABLE", verdict="VERDICT: CLEAN", comments=""):
    head = head or f"sha{n}"
    return {"number": n, "title": f"pr {n}", "headRefOid": head, "headRefName": f"b{n}",
            "createdAt": created or f"2026-01-0{n}T00:00:00Z", "mergeable": mergeable,
            "files": [{"path": f} for f in files],
            "reviews": [{"commit_id": head, "submitted_at": "2026-01-10T00:00:00Z", "body": f"ok\n{verdict}"}],
            "comments": comments}


def _run(prs, coordinate=None, **kw):
    gh, calls = fake_github(prs, **kw)
    mq.gh = gh
    sweep.gh = gh
    mq.gh_json = lambda args: json.loads(gh(args) or "null")
    mq.gh_lines = lambda args: [json.loads(l) for l in gh(args).splitlines() if l.strip()]
    sweep._last_dispatch[0] = 0.0
    rep = mq.run("o/r", coordinate=coordinate or (lambda r, g, log: None), log=lambda m: None,
                 wait=lambda s: None, now=lambda: 0.0)
    merges = [c[0] for c in calls if c[0][:2] == ["pr", "merge"]]
    dispatched = [json.loads(c[1])["client_payload"]["pr_number"] for c in calls if c[1] and "review-pr" in c[1]]
    comments = [c[0] for c in calls if c[0][:2] == ["pr", "comment"]]
    return rep, merges, dispatched, comments


def t_two_independent_prs_both_merge():
    rep, merges, disp, _ = _run([ghpr(1, {"a"}), ghpr(2, {"b"})])
    assert rep["merged"] == [1, 2] and disp == []
    assert all("--match-head-commit" in m for m in merges)


def t_two_overlapping_prs_merge_one_and_rereview_the_other():
    asked = []
    coord = lambda repo, g, log: asked.append([p.number for p in g]) or {"order": [2, 1], "hold": []}
    rep, merges, disp, _ = _run([ghpr(1, {"a"}), ghpr(2, {"a", "b"})], coordinate=coord)
    assert asked == [[1, 2]], asked
    assert rep["merged"] == [2] and rep["rereview"] == [1] and disp == ["1"]


def t_the_coordinator_is_never_asked_about_a_lone_pr():
    asked = []
    _run([ghpr(1, {"a"})], coordinate=lambda r, g, log: asked.append(g))
    assert asked == []


def t_a_held_pr_gets_one_comment_and_no_merge():
    coord = lambda repo, g, log: {"order": [1], "hold": [{"pr": 2, "reason": "undoes #1's change to a"}]}
    rep, merges, disp, comments = _run([ghpr(1, {"a"}), ghpr(2, {"a"})], coordinate=coord)
    assert rep["merged"] == [1] and rep["held"] == [2] and len(comments) == 1


def t_a_verdict_older_than_a_change_to_its_files_is_reviewed_again_not_merged():
    rep, merges, disp, _ = _run([ghpr(1, {"a"})], commits_since=["c1"], changed_files_by_sha={"c1": ["a"]})
    assert merges == [] and rep["rereview"] == [1] and disp == ["1"]


def t_a_change_to_other_files_leaves_the_verdict_fresh():
    rep, merges, disp, _ = _run([ghpr(1, {"a"})], commits_since=["c1"], changed_files_by_sha={"c1": ["z"]})
    assert rep["merged"] == [1]


def t_conflicting_blocking_and_unreviewed_never_merge():
    rep, merges, disp, comments = _run([ghpr(1, {"a"}, mergeable="CONFLICTING"),
                                        ghpr(2, {"b"}, verdict="VERDICT: BLOCKING"),
                                        ghpr(3, {"c"}, verdict="no verdict line")])
    assert merges == [] and rep["conflict"] == [1] and sorted(rep["waiting"]) == [2, 3] and len(comments) == 1


def t_dry_run_changes_nothing():
    gh, calls = fake_github([ghpr(1, {"a"}), ghpr(2, {"a"})])
    mq.gh = gh
    sweep.gh = gh
    mq.gh_json = lambda args: json.loads(gh(args) or "null")
    mq.gh_lines = lambda args: [json.loads(l) for l in gh(args).splitlines() if l.strip()]
    mq.run("o/r", dry=True, coordinate=lambda r, g, log: None, log=lambda m: None, wait=lambda s: None, now=lambda: 0.0)
    assert not [c for c in calls if c[0][:2] in (["pr", "merge"], ["pr", "comment"]) or (c[1] and "review-pr" in c[1])]


def run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("t_")]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
    return passed == len(tests)


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
