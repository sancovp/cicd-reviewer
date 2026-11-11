#!/usr/bin/env python3
"""Tests for outage.py — the model's check, the UNREVIEWED mark and the late review's close. No network, no sleeping.
Run: python3 tests/test_outage.py"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
for name in ("sweep", "outage"):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
import sweep  # noqa: E402
import outage  # noqa: E402


def answers(*codes):
    it, asked, slept = iter(codes), [], []
    return (lambda key, model: asked.append(1) or next(it)), asked, slept


def t_what_counts_as_down():
    assert outage.classify(200) == "up"
    for code in (0, 401, 403, 408, 429, 500, 502, 529):
        assert outage.classify(code) == "down", code
    for code in (400, 404, 422):
        assert outage.classify(code) == "broken", code


def t_down_only_after_every_try_a_minute_apart():
    ask, asked, slept = answers(429, 429, 429)
    assert outage.probe("k", "m", ask, slept.append) == ("down", 429)
    assert len(asked) == 3 and slept == [outage.APART, outage.APART]


def t_a_passing_burst_is_not_an_outage():
    ask, asked, slept = answers(429, 200)
    assert outage.probe("k", "m", ask, slept.append) == ("up", 200) and len(asked) == 2


def t_a_wrong_setting_fails_at_once_and_is_never_an_outage():
    ask, asked, slept = answers(400)
    assert outage.probe("k", "m", ask, slept.append) == ("broken", 400) and len(asked) == 1 and slept == []


def t_the_mark_is_a_verdict_the_queue_and_the_sweep_read():
    body = outage.unreviewed_body(429)
    assert sweep.verdict_of(body) == sweep.VERDICT_UNREVIEWED and "HTTP 429" in body


def t_the_late_verdict_is_the_newest_since_the_review_began():
    c = [{"created_at": "2026-01-01T00:00:00Z", "body": "old\nVERDICT: BLOCKING"},
         {"created_at": "2026-01-03T00:00:00Z", "body": "late\nVERDICT: CLEAN"}]
    assert outage.late_verdict(c, "2026-01-02T00:00:00Z") == sweep.VERDICT_CLEAN
    assert outage.late_verdict(c[:1], "2026-01-02T00:00:00Z") is None
    assert outage.late_verdict([{"created_at": "2026-01-03", "body": "x\nVERDICT: UNREVIEWED"}], "2026-01-02") is None


def _close(verdict_body, labels=(sweep.REVIEW_OWED,), stale_view=False, fail_create=False):
    """A fake GitHub for close_late. The label is real state: its removal by number succeeds once and answers 404 after,
    as GitHub's does (measured on #2495). `stale_view` makes every `pr view` see the label as it was when the runs
    began — two late reviews that both read before either wrote."""
    calls, state = [], {"labels": set(labels), "issues": 0}
    first = set(labels)

    def gh(args, input_text=None):
        calls.append(args)
        if args[:3] == ["api", "-X", "DELETE"]:
            if sweep.REVIEW_OWED not in state["labels"]:
                raise RuntimeError("gh api -X DELETE…: Label does not exist (HTTP 404)")
            state["labels"].discard(sweep.REVIEW_OWED)
            return "[]"
        if args[:2] == ["pr", "view"]:
            seen = first if stale_view else state["labels"]
            return json.dumps({"title": "the change", "url": "https://x/pull/9", "labels": [{"name": n} for n in seen]})
        if args[:2] == ["issue", "create"]:
            if fail_create:
                raise RuntimeError("gh issue create…: Server Error (HTTP 502)")
            state["issues"] += 1
        if args[:2] == ["pr", "edit"] and "--add-label" in args:
            state["labels"].add(args[args.index("--add-label") + 1])
        return ""
    outage.gh = gh
    outage.gh_json = lambda args: json.loads(gh(args) or "null")
    outage.gh_lines = lambda args: ([{"created_at": "2026-01-03T00:00:00Z", "body": verdict_body}]
                                    if verdict_body else [])
    run = lambda: outage.close_late("o/r", "9", "2026-01-02T00:00:00Z", log=lambda m: None)
    return run, calls, state


def _writes(calls):
    return [a for a in calls if a[:2] in (["issue", "create"], ["pr", "edit"]) or a[:3] == ["api", "-X", "DELETE"]]


def t_a_blocking_late_review_opens_a_fix_and_takes_the_label_off():
    run, calls, state = _close("a defect\nVERDICT: BLOCKING")
    assert run() == 0 and state["issues"] == 1 and sweep.REVIEW_OWED not in state["labels"]
    assert any(a[:2] == ["issue", "create"] and any("Fix owed: #9" in x for x in a) for a in calls)


def t_a_clean_late_review_only_takes_the_label_off():
    run, calls, state = _close("fine\nVERDICT: CLEAN")
    assert run() == 0 and state["issues"] == 0 and sweep.REVIEW_OWED not in state["labels"]


def t_no_late_verdict_keeps_the_label_for_the_next_sweep():
    run, calls, state = _close(None)
    assert run() == 1 and _writes(calls) == [] and sweep.REVIEW_OWED in state["labels"]


def t_no_late_verdict_after_the_label_came_off_is_nothing_to_do():
    run, calls, state = _close(None, labels=("bug",))
    assert run() == 0 and _writes(calls) == []


def t_a_second_late_review_after_the_label_came_off_opens_nothing():
    """the sweep lists owed reviews by a search, which can still list a pull request after its label came off"""
    run, calls, state = _close("a defect\nVERDICT: BLOCKING", labels=("bug",))
    assert run() == 0 and state["issues"] == 0 and not any(a[:2] == ["issue", "create"] for a in calls), calls


def t_two_overlapping_late_reviews_open_one_fix():
    """two late reviews of one pull request that both read the label before either took it off: the removal is the
    claim, GitHub answers the second 404, so one Fix owed issue is opened, never two"""
    run, calls, state = _close("a defect\nVERDICT: BLOCKING", stale_view=True)
    try:
        codes = [run(), run()]
    except RuntimeError as e:
        raise AssertionError(f"the second review must read the 404 as claimed, not fail: {e}")
    assert codes == [0, 0] and state["issues"] == 1, (codes, state)


def t_a_fix_that_cannot_be_opened_puts_the_label_back():
    """the label came off as the claim; when the Fix owed issue then fails to open, the label goes back on so the next
    sweep sends the review again, and the run fails"""
    run, calls, state = _close("a defect\nVERDICT: BLOCKING", fail_create=True)
    try:
        run()
        raise AssertionError("a Fix owed issue that could not be opened must fail the run")
    except RuntimeError:
        pass
    assert sweep.REVIEW_OWED in state["labels"] and state["issues"] == 0


def t_an_unreadable_label_list_counts_as_still_owed():
    outage.gh_json = lambda args: {"title": "the change"}
    assert outage.label_on("o/r", "9") is True


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
        except Exception as e:   # a crash is a failure of the case it happened in, never of the whole suite
            print(f"FAIL {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
    return passed == len(tests)


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
