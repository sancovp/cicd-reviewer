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


def _close(verdict_body):
    calls = []

    def gh(args, input_text=None):
        calls.append(args)
        if args[:2] == ["pr", "view"]:
            return json.dumps({"title": "the change", "url": "https://x/pull/9"})
        return ""
    outage.gh = gh
    outage.gh_json = lambda args: json.loads(gh(args) or "null")
    outage.gh_lines = lambda args: ([{"created_at": "2026-01-03T00:00:00Z", "body": verdict_body}]
                                    if verdict_body else [])
    rc = outage.close_late("o/r", "9", "2026-01-02T00:00:00Z", log=lambda m: None)
    return rc, calls


def t_a_blocking_late_review_opens_a_fix_and_takes_the_label_off():
    rc, calls = _close("a defect\nVERDICT: BLOCKING")
    assert rc == 0 and any(a[:2] == ["issue", "create"] and any("Fix owed: #9" in x for x in a) for a in calls)
    assert any(a[:2] == ["pr", "edit"] and sweep.REVIEW_OWED in a for a in calls)


def t_a_clean_late_review_only_takes_the_label_off():
    rc, calls = _close("fine\nVERDICT: CLEAN")
    assert rc == 0 and not any(a[:2] == ["issue", "create"] for a in calls)
    assert any(a[:2] == ["pr", "edit"] for a in calls)


def t_no_late_verdict_keeps_the_label_for_the_next_sweep():
    rc, calls = _close(None)
    assert rc == 1 and calls == []


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
