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


def pr(state="OPEN", mergeable="MERGEABLE", head="aaaa1111", reviews=(), comments=0, run=None):
    return {"state": state, "mergeable": mergeable, "headRefOid": head,
            "reviews": [{"commit": {"oid": oid}, "body": body, "submittedAt": f"2026-10-11T0{i}:00:00Z"}
                        for i, (oid, body) in enumerate(reviews)],
            "comments": [{"body": "c"}] * comments, "reviewRun": run}


def run(status="completed", conclusion="success", id=42):
    return {"id": id, "status": status, "conclusion": conclusion}


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


def t_a_failed_review_run_exits_at_once():
    # #2435: the first attempt of the trigger's run at its tip failed before any job started, so no review came, and a
    # watch reading only the reviews waits toward its cap; Actions refusing jobs for billing left every watch the same way
    w = World(pr(run=run(conclusion="failure", id=77)))
    assert w.run() == 2 and w.i == 1 and "REVIEW-FAILED" in w.lines[-1] and "gh run rerun 77" in w.lines[-1]
    for ended in ("startup_failure", "timed_out", "action_required"):
        assert World(pr(run=run(conclusion=ended))).run() == 2


def t_a_review_run_failing_while_watched_exits():
    w = World(pr(run=run(status="in_progress", conclusion=None)), pr(run=run(conclusion="failure")))
    assert w.run() == 2 and w.i == 2 and "REVIEW-FAILED" in w.lines[-1]


def t_a_running_or_rerun_review_keeps_waiting_until_it_lands():
    w = World(pr(run=run(status="queued", conclusion=None)), pr(run=run(status="in_progress", conclusion=None)),
              pr(run=run(), reviews=[("aaaa1111", CLEAN)]), pr(state="MERGED", run=run()))
    assert w.run() == 0 and w.i == 4 and "MERGED" in w.lines[-1]


def t_a_verdict_a_cancelled_run_or_a_draft_skip_is_no_failure():
    w = World(pr(run=run(conclusion="failure"), reviews=[("aaaa1111", CLEAN)]), pr(state="MERGED"))
    assert w.run() == 0 and w.i == 2
    # the trigger's concurrency group cancels a run a newer one superseded: no news about the review
    for ended in ("cancelled", "skipped"):
        w = World(pr(run=run(conclusion=ended)), pr(state="MERGED"))
        assert w.run() == 0 and w.i == 2


def t_review_run_decides_by_every_run_at_the_tip():
    def runs(*rs):
        return lambda args: {"workflow_runs": [
            {"name": pw.REVIEW_TRIGGER, "id": i, "status": st, "conclusion": c, "created_at": f"2026-11-09T18:0{i}:00Z"}
            for i, (st, c) in enumerate(rs)] + [
            {"name": "Publish on main (path-gated)", "id": 99, "status": "completed", "conclusion": "failure",
             "created_at": "2026-11-09T19:00:00Z"}]}
    done = lambda c: ("completed", c)
    # #2423's tip: a draft's skipped run, then a ready_for_review run the next push cancelled — the latest decides
    assert pw.review_run("o/r", "abc", runs(done("skipped"), done("cancelled")))["conclusion"] == "cancelled"
    # a run that dispatched the review outranks a later cancelled one, and a running one outranks both
    assert pw.review_run("o/r", "abc", runs(done("success"), done("cancelled")))["id"] == 0
    assert pw.review_run("o/r", "abc", runs(done("success"), ("in_progress", None)))["id"] == 1
    assert pw.review_run("o/r", "abc", runs(done("failure")))["conclusion"] == "failure"
    calls = []
    def api(args):
        calls.append(args)
        return {"workflow_runs": []}
    assert pw.review_run("o/r", "abc", api) is None and "repos/o/r/actions/runs?head_sha=abc&event=pull_request" in calls[0][1]
    assert pw.review_run(None, "abc", api) is None and "repos/{owner}/{repo}/" in calls[1][1]
    assert pw.review_run("o/r", "", api) is None and len(calls) == 2


def t_a_failed_run_with_no_id_names_the_commit_not_none():
    w = World(pr(run={"status": "completed", "conclusion": "failure"}))
    assert w.run() == 2 and "None" not in w.lines[-1] and "gh run list --commit aaaa1111" in w.lines[-1]


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
