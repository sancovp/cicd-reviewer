#!/usr/bin/env python3
"""Tests for sweep.py's decisions — pure, no network. Run: python3 tests/test_sweep.py"""
import importlib.util
import os
import sys

_P = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sweep.py")
_spec = importlib.util.spec_from_file_location("sweep", _P)
sweep = importlib.util.module_from_spec(_spec)
sys.modules["sweep"] = sweep
_spec.loader.exec_module(sweep)
Branch, Facts, decide = sweep.Branch, sweep.Facts, sweep.decide


def facts(**kw):
    base = dict(repo="o/r", default="main", branch=Branch("work", "abc"), in_default=False)
    base.update(kw)
    return Facts(**base)


def t_standing_and_default_are_never_touched():
    assert decide(facts(branch=Branch("om-is-the-base", "x"))).action == "keep"
    assert decide(facts(branch=Branch("main", "x"))).action == "keep"


def t_a_tip_already_on_the_default_branch_is_deleted():
    assert decide(facts(in_default=True)).action == "delete"


def t_a_squash_merged_branch_is_deleted_only_at_the_merged_tip():
    assert decide(facts(merged_pr_tips=["abc"])).action == "delete"
    # new work pushed after the merge: the tip differs, so it is NOT deleted — it gets a pull request
    assert decide(facts(merged_pr_tips=["older"])).action == "open"


def t_no_pull_request_gets_one():
    assert decide(facts()).action == "open"


def t_open_pr_clean_and_mergeable_is_merged():
    p = decide(facts(open_pr={"number": 7, "mergeable": "MERGEABLE", "head_sha": "abc"}, verdict=sweep.VERDICT_CLEAN))
    assert (p.action, p.pr) == ("merge", 7)


def t_open_pr_clean_but_mergeability_unknown_waits_for_a_review_not_a_merge():
    p = decide(facts(open_pr={"number": 7, "mergeable": "UNKNOWN", "head_sha": "abc"}, verdict=sweep.VERDICT_CLEAN))
    assert p.action == "review"


def t_conflict_is_stuck_even_when_clean():
    p = decide(facts(open_pr={"number": 7, "mergeable": "CONFLICTING", "head_sha": "abc"}, verdict=sweep.VERDICT_CLEAN))
    assert p.action == "stuck"


def t_blocking_is_stuck():
    p = decide(facts(open_pr={"number": 7, "mergeable": "MERGEABLE", "head_sha": "abc"}, verdict=sweep.VERDICT_BLOCKING))
    assert p.action == "stuck"


def t_no_verdict_dispatches_a_review():
    assert decide(facts(open_pr={"number": 7, "mergeable": "MERGEABLE", "head_sha": "abc"})).action == "review"


def t_verdict_is_read_from_the_last_line_only():
    assert sweep.verdict_of("all good\n\nVERDICT: CLEAN\n") == sweep.VERDICT_CLEAN
    assert sweep.verdict_of("VERDICT: CLEAN\nbut then more text") is None
    assert sweep.verdict_of("no verdict here") is None
    assert sweep.verdict_of("x\nVERDICT: BLOCKING") == sweep.VERDICT_BLOCKING


def t_a_verdict_on_an_older_tip_does_not_count():
    reviews = [{"commit_id": "old", "submitted_at": "2026-01-02", "body": "VERDICT: CLEAN"},
               {"commit_id": "abc", "submitted_at": "2026-01-01", "body": "looked\nVERDICT: BLOCKING"}]
    assert sweep.last_verdict(reviews, "abc") == sweep.VERDICT_BLOCKING
    assert sweep.last_verdict(reviews, "new") is None


def t_the_newest_verdict_on_the_tip_wins():
    reviews = [{"commit_id": "abc", "submitted_at": "2026-01-01", "body": "VERDICT: BLOCKING"},
               {"commit_id": "abc", "submitted_at": "2026-01-02", "body": "fixed\nVERDICT: CLEAN"}]
    assert sweep.last_verdict(reviews, "abc") == sweep.VERDICT_CLEAN


def t_tracking_body_lists_only_stuck():
    plans = [sweep.Plan("o/r", "a", "stuck", "conflicts", 3), sweep.Plan("o/r", "b", "delete", "on main")]
    body = sweep.tracking_body(plans)
    assert "`a`" in body and "#3" in body and "`b`" not in body
    assert "Nothing stuck" in sweep.tracking_body([sweep.Plan("o/r", "b", "delete", "x")])


def t_act_never_touches_anything_in_a_dry_run():
    calls = []
    sweep.gh = lambda *a, **k: calls.append(a) or ""
    p = sweep.Plan("o/r", "work", "delete", "x")
    sweep.act(p, "main", Branch("work", "abc"), "o", True, print)
    assert calls == []


def _fake_gh(responses, calls):
    def fake(args, input_text=None):
        calls.append(args)
        key = " ".join(args[:2])
        for k, v in responses:
            if " ".join(args).startswith(k):
                return v
        return ""
    return fake


def _merge_with(view, reviews, comments=""):
    import json as _j
    calls = []
    sweep.gh = _fake_gh([("pr view", _j.dumps(view)),
                         ("api repos/o/r/pulls/7/reviews", "\n".join(_j.dumps(r) for r in reviews)),
                         ("api repos/o/r/issues/7/comments", comments)], calls)
    out = sweep.merge_pr("o/r", 7, lambda m: None, wait=lambda s: None)
    return out, calls


def t_merge_pr_merges_a_clean_mergeable_tip_and_matches_the_head():
    view = {"state": "OPEN", "mergeable": "MERGEABLE", "headRefOid": "abc", "baseRefName": "main"}
    out, calls = _merge_with(view, [{"commit_id": "abc", "submitted_at": "1", "body": "ok\nVERDICT: CLEAN"}])
    assert out == "merged"
    merge = [c for c in calls if c[:2] == ["pr", "merge"]][0]
    assert "--match-head-commit" in merge and "abc" in merge and "--squash" in merge


def t_merge_pr_refuses_a_verdict_on_an_older_tip():
    view = {"state": "OPEN", "mergeable": "MERGEABLE", "headRefOid": "new", "baseRefName": "main"}
    out, calls = _merge_with(view, [{"commit_id": "old", "submitted_at": "1", "body": "VERDICT: CLEAN"}])
    assert out == "no-verdict" and not [c for c in calls if c[:2] == ["pr", "merge"]]


def t_merge_pr_never_merges_blocking():
    view = {"state": "OPEN", "mergeable": "MERGEABLE", "headRefOid": "abc", "baseRefName": "main"}
    out, calls = _merge_with(view, [{"commit_id": "abc", "submitted_at": "1", "body": "VERDICT: BLOCKING"}])
    assert out == "blocking" and not [c for c in calls if c[:2] == ["pr", "merge"]]


def t_merge_pr_comments_a_conflict_once():
    view = {"state": "OPEN", "mergeable": "CONFLICTING", "headRefOid": "abc123456789xyz", "baseRefName": "main"}
    out, calls = _merge_with(view, [{"commit_id": "abc123456789xyz", "submitted_at": "1", "body": "VERDICT: CLEAN"}])
    assert out == "conflict" and [c for c in calls if c[:2] == ["pr", "comment"]]
    out, calls = _merge_with(view, [], comments="This pull request conflicts with `main` at abc123456789 …")
    assert out == "conflict" and not [c for c in calls if c[:2] == ["pr", "comment"]]


def t_merge_pr_skips_a_closed_pull_request():
    out, calls = _merge_with({"state": "MERGED", "mergeable": "UNKNOWN", "headRefOid": "abc", "baseRefName": "main"}, [])
    assert out == "not-open"


def t_a_publish_target_never_gets_a_merge_or_a_pull_request():
    p = decide(facts(publish_source="base/chaincompiler"))
    assert p.action == "stuck" and "base/chaincompiler" in p.why
    p = decide(facts(publish_source="x", open_pr={"number": 4, "mergeable": "MERGEABLE", "head_sha": "abc"},
                     verdict=sweep.VERDICT_CLEAN))
    assert p.action == "stuck" and p.pr == 4


def t_a_publish_targets_merged_branch_is_still_deleted():
    assert decide(facts(publish_source="x", in_default=True)).action == "delete"


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
