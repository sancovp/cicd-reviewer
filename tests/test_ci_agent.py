#!/usr/bin/env python3
"""Unit tests for ci_agent.extract_text — the pure result-parsing logic.

build_agent()/main() need heaven-framework + a live MiniMax model, so they are covered
by the container E2E run (automation/cicd-reviewer task 5), not here.

Run: python3 tests/test_ci_agent.py
"""
import importlib.util
import os
import sys

# Load ci_agent by path (it's a CLI script, not an installed package). extract_text needs
# no heaven-framework, and ci_agent imports heaven lazily inside build_agent(), so this is cheap.
_CI_AGENT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ci_agent.py")
_spec = importlib.util.spec_from_file_location("ci_agent", _CI_AGENT)
ci_agent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ci_agent)
extract_text = ci_agent.extract_text


# Class name must be exactly "AIMessage" — extract_text keys on __class__.__name__,
# mirroring langchain's real AIMessage (same check as grug_agent.py).
class AIMessage:
    def __init__(self, content):
        self.content = content


class _Human:  # non-AIMessage class name on purpose
    def __init__(self, content):
        self.content = content


class _History:
    def __init__(self, messages):
        self.messages = messages


def t_non_dict_stringified():
    assert extract_text("plain string") == "plain string"
    assert extract_text(None) == "None"


def t_prepared_message_wins():
    hist = _History([AIMessage("from history")])
    assert extract_text({"prepared_message": "prep", "history": hist}) == "prep"


def t_last_aimessage_from_history():
    hist = _History([AIMessage("first"), _Human("noise"), AIMessage("last review DONE")])
    assert extract_text({"history": hist}) == "last review DONE"


def t_empty_dict_returns_empty():
    assert extract_text({}) == ""
    assert extract_text({"history": _History([])}) == ""


def t_non_string_aimessage_content_coerced():
    hist = _History([AIMessage(["a", "b"])])
    assert extract_text({"history": hist}) == "['a', 'b']"


def t_harvest_prompt_names_skill_branch_and_gate():
    # MODE=harvest routes to a prompt that names the skill, the branch convention, and the
    # never-self-approve gate — the load-bearing constraints of the self-maintenance loop.
    p = ci_agent._harvest_prompt("/repo", "owner/repo")
    assert "harvest-rules-from-reviews" in p
    assert "cicd-rules/" in p
    assert "never approve or merge" in p
    assert "owner/repo" in p and "/repo" in p


def t_review_prompt_demands_the_verdict_line():
    p = ci_agent._review_prompt("/repo", "o/r", "7", "main", "work")
    assert "VERDICT: CLEAN" in p and "VERDICT: BLOCKING" in p and "--comment" in p


def t_a_review_counts_only_with_a_verdict_on_the_tip_posted_this_run():
    vp = ci_agent.verdict_posted
    ok = {"commit_id": "t", "submitted_at": "2026-01-02T00:00:00Z", "body": "fine\nVERDICT: CLEAN"}
    assert vp([ok], "t", "2026-01-01T00:00:00Z")
    assert not vp([ok], "other", "2026-01-01T00:00:00Z")                 # another tip
    assert not vp([ok], "t", "2026-01-03T00:00:00Z")                     # posted before this run
    assert not vp([dict(ok, body="fine, but no verdict")], "t", "2026-01-01T00:00:00Z")
    assert not vp([], "t", "2026-01-01T00:00:00Z")


def t_the_late_review_comments_on_the_merged_pr_and_demands_the_verdict_line():
    p = ci_agent._late_review_prompt("o/r", "9")
    assert "MERGED" in p and "gh pr diff 9 --repo o/r" in p and "gh pr comment 9 --repo o/r" in p
    assert "VERDICT: CLEAN" in p and "VERDICT: BLOCKING" in p


def t_a_late_review_counts_only_with_a_verdict_comment_posted_this_run():
    lp = ci_agent.late_verdict_posted
    ok = {"created_at": "2026-01-02T00:00:00Z", "body": "read it\nVERDICT: BLOCKING"}
    assert lp([ok], "2026-01-01T00:00:00Z")
    assert not lp([ok], "2026-01-03T00:00:00Z")
    assert not lp([dict(ok, body="no verdict")], "2026-01-01T00:00:00Z")
    src = open(_CI_AGENT).read()
    assert 'if mode == "review-merged":\n        return _late_review_landed(' in src


def t_coordinate_prompt_names_the_skill_the_output_and_forbids_acting():
    p = ci_agent._coordinate_prompt("o/r", '[{"number": 1}]')
    assert "coordinate-merges" in p and "/out/decision.json" in p and "do not merge" in p and "o/r" in p


def t_the_agent_runs_in_heavens_agent_mode_with_many_rounds():
    import re
    cmd = ci_agent.agent_mode("review PR #7, then post it")
    m = re.search(r"agent goal=(.*?), iterations=(\d+)", cmd, re.IGNORECASE | re.DOTALL)   # heaven's own parser
    assert m and m.group(1) == "review PR #7, then post it" and int(m.group(2)) >= 50
    assert ci_agent.ROUND_STEPS <= 20


def t_no_single_round_run_and_the_result_is_checked():
    src = open(_CI_AGENT).read()
    assert "POST_BY" not in src and "MAX_TOOL_CALLS" not in src
    assert "agent.run(prompt=agent_mode(prompt))" in src and "if not result_exists(" in src


def t_harvest_alone_reads_its_result_off_the_text():
    assert ci_agent.result_exists("harvest", "all done", "o/r", "x")
    assert not ci_agent.result_exists("harvest", "still working", "o/r", "x")


def _rv(sha, at, body):
    return {"commit_id": sha, "submitted_at": f"2026-11-28T0{at}:00:00Z", "body": body}


def t_a_review_blocks_only_on_the_prs_own_defect_and_owes_the_rest():
    # the README generator's PR went through about ten review rounds, most on a side piece outside its purpose
    for p in (ci_agent._review_prompt("/repo", "o/r", "7", "main", "work"), ci_agent._late_review_prompt("o/r", "9")):
        assert "what the pull request is for" in p and "gh pr view" in p and "_states.md" in p
        assert "BLOCKING only when the pull request's own change adds the defect or makes it worse" in p
        assert ci_agent.BLOCKING_MARK + ": <path:line>" in p and ci_agent.OWED_MARK + " (<the folder" in p
        assert "never blocks" in p and "\\" not in p
    assert "OWED findings may sit above it" in ci_agent._review_prompt("/repo", "o/r", "7", "main", "work")


def t_the_last_reviewed_tip_is_the_newest_verdict_on_another_tip():
    lr = ci_agent.last_reviewed
    rs = [_rv("a", 1, "x\n- BLOCKING: `f.py:1` — crash\nVERDICT: BLOCKING"), _rv("b", 2, "y\nVERDICT: CLEAN"),
          _rv("c", 3, "the model did not answer\nVERDICT: UNREVIEWED"), _rv("d", 4, "a note, no verdict")]
    assert lr(rs, "head")["commit_id"] == "b" and lr(rs, "head")["verdict"] == "VERDICT: CLEAN"
    assert lr(rs[:1], "head")["commit_id"] == "a"
    assert lr(rs[2:], "head") is None and lr([], "head") is None          # UNREVIEWED and no verdict are no review
    # this very tip already has a verdict: the queue's freshness review, read whole against the new default branch —
    # and an UNREVIEWED tip sent back because it overlaps what just merged is read whole the same way
    assert lr(rs + [_rv("head", 5, "z\nVERDICT: CLEAN")], "head") is None
    assert lr(rs + [_rv("head", 5, "the model did not answer\nVERDICT: UNREVIEWED")], "head") is None
    # a note on this tip with no verdict leaves the last reviewed tip as it was
    assert lr(rs + [_rv("head", 5, "a note")], "head")["commit_id"] == "b"


def t_the_next_tips_review_reads_what_changed_and_what_it_blocked_on():
    prior = dict(_rv("a1b2c3", 1, "two things\n- BLOCKING: `f.py:1` — crash on []\n- OWED (base/x): `g.py:2` — old\n"
                                   "VERDICT: BLOCKING"), verdict="VERDICT: BLOCKING")
    p = ci_agent._review_prompt("/repo", "o/r", "7", "main", "work", prior)
    assert "already reviewed at `a1b2c3`" in p and "`git -C /repo diff a1b2c3 HEAD`" in p and "Review ONLY what changed" in p
    assert "`f.py:1` — crash on []" in p and "g.py:2" not in p                     # what it blocked on, not what it owed
    assert "only what changed since that tip" in p
    assert "already reviewed" not in ci_agent._review_prompt("/repo", "o/r", "7", "main", "work")
    # a review from before the marked lines gives its whole body; a CLEAN one blocked on nothing
    old = dict(_rv("a", 1, "line 4 crashes\nVERDICT: BLOCKING"), verdict="VERDICT: BLOCKING")
    assert ci_agent.blocked_findings(old) == "line 4 crashes"
    assert "none" in ci_agent.blocked_findings(dict(_rv("a", 1, "ok\nVERDICT: CLEAN"), verdict="VERDICT: CLEAN"))
    huge = dict(_rv("a", 1, "x" * 50000 + "\nVERDICT: BLOCKING"), verdict="VERDICT: BLOCKING")
    assert len(ci_agent.blocked_findings(huge)) == ci_agent.PRIOR_FINDINGS_MAX


def t_a_new_tip_reads_on_only_from_an_ancestor_with_no_default_branch_merged_in_since():
    # `git diff <tip> HEAD` is the pull request's own change only when no merge of the default branch came in since
    # the tip; after one, it carries the default branch's lines, and a review of them blocks on what the PR never wrote
    rs = [_rv("a", 1, "ok\nVERDICT: CLEAN"), _rv("b", 2, "ok\nVERDICT: CLEAN")]

    def world(ancestors, mbs, head="head"):
        def git(*a):
            if a[:2] == ("merge-base", "--is-ancestor"):
                return (0 if a[2] in ancestors else 1), ""
            mb = mbs.get(a[2])
            return (0, mb) if mb else (1, "")
        saved = ci_agent._reviews, ci_agent._head
        ci_agent._reviews, ci_agent._head = (lambda g, p: rs), (lambda g, p: head)
        try:
            got = ci_agent.prior_tip("/repo", "o/r", "7", "main", git=git)
        finally:
            ci_agent._reviews, ci_agent._head = saved
        return got and got["commit_id"]
    assert world({"a", "b"}, {"HEAD": "m1", "a": "m1", "b": "m1"}) == "b"
    assert world({"a", "b"}, {"HEAD": "m2", "a": "m1", "b": "m2"}) == "b"
    assert world({"a", "b"}, {"HEAD": "m2", "a": "m1", "b": "m1"}) is None        # the default branch merged in since
    assert world({"a"}, {"HEAD": "m1", "a": "m1", "b": "m1"}) == "a"               # b rewritten away: the older ancestor
    assert world(set(), {"HEAD": "m1", "a": "m1", "b": "m1"}) is None               # a rewritten history
    assert world({"a", "b"}, {"a": "m1", "b": "m1"}) is None                        # no merge base for the head
    assert world({"a", "b"}, {"HEAD": "m1", "a": "m1", "b": "m1"}, head="") is None  # the head could not be read
    src = open(_CI_AGENT).read()
    assert 'prior = prior_tip(repo, gh_repo, pr, os.environ.get("BASE_REF", "") or "main")' in src
    assert 'os.environ.get("HEAD_REF", ""), prior,' in src


def t_a_review_whose_findings_disagree_with_its_verdict_is_no_result():
    vp, lp = ci_agent.verdict_posted, ci_agent.late_verdict_posted
    bad = "- BLOCKING: `f.py:1` — crash\nVERDICT: CLEAN"
    assert not vp([{"commit_id": "t", "submitted_at": "2026-01-02T00:00:00Z", "body": bad}], "t", "2026-01-01T00:00:00Z")
    assert not lp([{"created_at": "2026-01-02T00:00:00Z", "body": bad}], "2026-01-01T00:00:00Z")
    good = "- OWED (base/x): `g.py:2` — old\n- FIXED: `f.py:1` — guarded\nVERDICT: CLEAN"
    assert vp([{"commit_id": "t", "submitted_at": "2026-01-02T00:00:00Z", "body": good}], "t", "2026-01-01T00:00:00Z")
    # read as the queue reads it: BLOCKING, so the next tip carries that line
    assert ci_agent.last_reviewed([_rv("a", 1, bad)], "head")["verdict"] == "VERDICT: BLOCKING"
    assert "f.py:1" in ci_agent.blocked_findings(ci_agent.last_reviewed([_rv("a", 1, bad)], "head"))
    assert ci_agent.FIXED_MARK in ci_agent._review_prompt("/repo", "o/r", "7", "main", "w", dict(_rv("a", 1, bad),
                                                                                              verdict="VERDICT: BLOCKING"))


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
