#!/usr/bin/env python3
"""Tests for pr_watch.py — the watch against a fake GitHub and a fake clock. No network, no sleeping.
Each test is a failure a hand-written watch loop had. Run: python3 tests/test_pr_watch.py"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
for name in ("sweep", "pr_watch"):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
import pr_watch as pw  # noqa: E402

CLEAN = "Looks fine.\n\nVERDICT: CLEAN"
BLOCK = "A defect.\n\nVERDICT: BLOCKING"


def pr(state="OPEN", mergeable="MERGEABLE", head="aaaa1111", reviews=(), comments=0):
    return {"state": state, "mergeable": mergeable, "headRefOid": head,
            "reviews": [{"commit": {"oid": oid}, "body": body, "submittedAt": f"2026-10-11T0{i}:00:00Z"}
                        for i, (oid, body) in enumerate(reviews)],
            "comments": [{"body": "c"}] * comments}


class World:
    """A fake GitHub answering a script of states (the last repeats), and a clock that advances by each sleep."""
    def __init__(self, *answers):
        self.answers, self.i, self.t, self.lines = list(answers), 0, 0.0, []

    def fetch(self):
        a = self.answers[min(self.i, len(self.answers) - 1)]
        self.i += 1
        if isinstance(a, Exception):
            raise a
        return a

    def run(self, **kw):
        return pw.watch(7, self.fetch, sleep=lambda s: setattr(self, "t", self.t + s), now=lambda: self.t,
                        out=self.lines.append, **kw)


def t_already_merged_exits_at_once():
    # the #1599 watch: started after the merge, its baseline was MERGED, nothing ever changed, it ran all night
    w = World(pr(state="MERGED"))
    assert w.run() == 0 and w.i == 1 and "MERGED" in w.lines[-1]


def t_already_conflicting_or_blocked_exits_at_once():
    assert World(pr(mergeable="CONFLICTING")).run() == 2
    assert World(pr(reviews=[("aaaa1111", BLOCK)])).run() == 2


def t_conflict_appearing_exits():
    # the #1561 watch printed CONFLICTING three times and kept looping
    w = World(pr(), pr(), pr(mergeable="CONFLICTING"))
    assert w.run() == 2 and "CONFLICT" in w.lines[-1]


def t_clean_verdict_and_unknown_flicker_keep_waiting_then_merge_exits():
    # the #1566 watch treated CLEAN as a change and had to be patched by hand to keep going
    w = World(pr(), pr(mergeable="UNKNOWN"), pr(reviews=[("aaaa1111", CLEAN)]), pr(state="MERGED", mergeable="UNKNOWN"))
    assert w.run() == 0 and w.i == 4 and "MERGED" in w.lines[-1]


def t_verdict_on_an_older_tip_does_not_count():
    w = World(pr(head="bbbb2222", reviews=[("aaaa1111", BLOCK)]), pr(head="bbbb2222", state="MERGED"))
    assert w.run() == 0


def t_new_comment_and_a_push_exit():
    assert World(pr(), pr(comments=1)).run() == 2
    w = World(pr(), pr(head="cccc3333"))
    assert w.run() == 2 and "PUSHED" in w.lines[-1]


def t_a_deploy_previews_comment_keeps_waiting():
    # every pull request got the Cloudflare preview's status comment, and every watch exited on it for nothing
    bot = {"author": {"login": "cloudflare-workers-and-pages"}, "body": "Deploying Preview"}
    w = World(pr(), dict(pr(), comments=[bot]), pr(state="MERGED"))
    assert w.run() == 0 and w.i == 3 and "MERGED" in w.lines[-1]
    person = {"author": {"login": "sancovp"}, "body": "held: wait for #12"}
    assert World(pr(), dict(pr(), comments=[bot, person])).run() == 2


def t_merged_at_another_tip_than_expected():
    assert World(pr(state="MERGED", head="aaaa1111")).run(expect="aaaa1111ffff") == 0
    w = World(pr(state="MERGED", head="aaaa1111"))
    assert w.run(expect="dddd4444") == 4 and "new PR" in w.lines[-1]


def t_never_runs_past_its_cap():
    w = World(pr())
    assert w.run(interval=60, max_hours=1) == 3 and "TIMEOUT" in w.lines[-1] and w.t <= 3600 + 60


def t_gh_failures_retry_then_give_up():
    w = World(RuntimeError("502"), RuntimeError("502"), pr(state="MERGED"))
    assert w.run() == 0
    w = World(RuntimeError("401"))
    assert w.run(max_failures=3) == 5 and w.i == 3


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
