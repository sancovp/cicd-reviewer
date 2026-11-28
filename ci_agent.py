#!/usr/bin/env python3
"""CICD Reviewer — headless heaven review agent (one-shot, CI).

Runs inside the CI container. Its process cwd MUST be the cicd_aios AIOS directory
(the entrypoint chdir's there) so heaven-framework's resolve_devdirs auto-loads the
AIOS's .claude/rules + .claude/skills into the system prompt. The repo under review is
checked out at /repo (its own git repo); the agent operates on it via bash `-C /repo`.

Pattern mirrors integration/observatory-sdna/container/grug_agent.py (BaseHeavenAgent +
UnifiedChat + History, tools=[BashTool], provider=ANTHROPIC, model=MiniMax-M3). MiniMax
is auto-selected by unified_chat.py when model starts with "minimax" (needs MINIMAX_API_KEY).

Env:
  MODE               review | review-merged | pr | harvest | coordinate   (which task to run; review-merged = the late
                     review of a pull request merged while the model was down)
  COORD_INPUT        (coordinate mode) JSON list of the overlapping CLEAN pull requests
  REPO_DIR           checked-out repo path (default /repo)
  GITHUB_REPOSITORY  owner/name
  PR_NUMBER          (review mode) the PR to review
  BASE_REF HEAD_REF  branch refs
  MINIMAX_API_KEY    model credential (required)
  GITHUB_TOKEN       for gh (required for posting)
  HEAVEN_DATA_DIR    heaven state dir (required by heaven; fresh in container)
"""
import asyncio
import logging
import os
import sys

# THE AGENT RUNS IN HEAVEN'S AGENT MODE — one conversation, ITERATIONS rounds of at most ROUND_STEPS tool calls each,
# ending when the agent declares its goal accomplished (heaven's TaskSystemTool). A plain prompt would run ONE round,
# so a large job stopped half-way; `agent goal=…, iterations=N` is heaven's own form for running until done.
ROUND_STEPS = int(os.environ.get("CICD_ROUND_STEPS", "15"))
ITERATIONS = int(os.environ.get("CICD_ITERATIONS", "100"))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s cicd_reviewer: %(message)s"
)
log = logging.getLogger("cicd_reviewer")

BASE_SYSTEM_PROMPT = (
    "You are running as the CICD Reviewer in a CI container. Your full identity, rules, "
    "and skills are provided in the <DEVDIR_CONTEXT> and <AVAILABLE_SKILLS> sections that "
    "follow — read them and follow them exactly. Use your BashTool to inspect the repo at "
    "/repo (always with an explicit path, e.g. `git -C /repo ...`) and to post results with "
    "`gh`. When the deliverable is produced, end your final message with DONE."
)


# A REVIEW CONVERGES (DESIGN.md §11): a finding is BLOCKING only when the PR's own change adds it or makes it worse, in
# what the PR is for; every other finding is OWED to the board of the project it belongs to and never blocks. Each is
# one line of the review, so the PR watch and the next review read them without the model.
BLOCKING_MARK = "- BLOCKING"
OWED_MARK = "- OWED"
FIXED_MARK = "- FIXED"   # a finding the last review blocked on, fixed since: never written with the BLOCKING mark
# the findings an earlier review blocked on, carried into the review of the next tip, are cut to this many characters
PRIOR_FINDINGS_MAX = 6000


def _classify(pr, gh_repo):
    return (
        f"First read what the pull request is for — `gh pr view {pr} --repo {gh_repo} --json title,body` and the board "
        f"of the project it changes (its `.claude/rules/*_states.md`): the version it carries is what it is for. Then "
        f"classify every finding: BLOCKING only when the pull request's own change adds the defect or makes it worse, in "
        f"what the pull request is for; every other finding — a defect that was there before, one in a part the pull "
        f"request only touches in passing, a wording, a note — is OWED and never blocks. Write each finding on one line, "
        f"{BLOCKING_MARK}: <path:line> — <failure>   or   {OWED_MARK} (<the folder of the project it belongs to>): "
        f"<path:line> — <finding>. "
    )


def _review_prompt(repo, gh_repo, pr, base, head, prior=None):
    """The review of one tip. `prior` — the reviewed tip `prior_tip` reads on from — makes it the review of what changed
    since that tip, together with the findings that review blocked on."""
    since = ""
    if prior:
        since = (
            f"This pull request was already reviewed at `{prior['commit_id']}` ({prior['verdict']}). Review ONLY what "
            f"changed since that tip: `git -C {repo} diff {prior['commit_id']} HEAD` — no merge of the default branch "
            f"came in since it, so every line of that diff is the pull request's own. Do not review the rest of the pull "
            f"request again: a defect you see outside what changed is OWED, never BLOCKING. Check every finding that "
            f"review blocked on: fixed ⇒ one line `{FIXED_MARK}: <path:line> — <what fixed it>`; not fixed ⇒ it stays a "
            f"{BLOCKING_MARK} line. The findings it blocked on:\n{blocked_findings(prior)}\n"
        )
    return (
        f"MODE=review. Review pull request #{pr} on {gh_repo}: head `{head}` against base "
        f"`{base}`. The repo is checked out at {repo}. Follow the `review-pr-diff` skill. {_classify(pr, gh_repo)}"
        f"{since}Read the diff{' (only what changed since that tip)' if prior else ''}, find real "
        f"correctness/security/contract issues per your review-discipline rule (cite path:line, trace each to an exact symptom, drop vague ones), and post your "
        f"review with `gh pr review {pr} --repo {gh_repo} --comment --body-file <file>`. The review's LAST LINE must be "
        f"exactly `VERDICT: CLEAN` (no BLOCKING finding; OWED findings may sit above it) or `VERDICT: BLOCKING` (at least "
        f"one BLOCKING finding) — the merge queue merges the pull request on CLEAN. "
        f"End with DONE."
    )


def _late_review_prompt(gh_repo, pr):
    return (
        f"MODE=review-merged. Pull request #{pr} on {gh_repo} was MERGED while the reviewer's model was down, so nobody "
        f"has reviewed it. Review it now: read its diff with `gh pr diff {pr} --repo {gh_repo}` (the default branch is "
        f"checked out at /repo for context), and find real correctness/security/contract issues per the `review-pr-diff` "
        f"skill and your review-discipline rule (cite path:line, trace each to an exact symptom, drop vague ones). "
        f"{_classify(pr, gh_repo)}Post "
        f"your review as a comment with `gh pr comment {pr} --repo {gh_repo} --body-file <file>`. Its LAST LINE must be "
        f"exactly `VERDICT: CLEAN` or `VERDICT: BLOCKING` — a BLOCKING verdict opens a fix issue, and every finding line "
        f"is carried into the issue the CI opens. End with DONE."
    )


VERDICT_UNREVIEWED = "VERDICT: UNREVIEWED"


def _verdict(body, lines_allowed=None):
    """A review's verdict, read as `sweep.verdict_of` reads it: a CLEAN one under a standing BLOCKING line is BLOCKING."""
    lines = [l.strip() for l in (body or "").strip().splitlines() if l.strip()]
    if not lines or lines[-1] not in (lines_allowed or VERDICT_LINES):
        return None
    if lines[-1] == "VERDICT: CLEAN" and any(l.startswith(BLOCKING_MARK) for l in lines):
        return "VERDICT: BLOCKING"
    return lines[-1]


def last_reviewed(reviews, head_sha, usable=None):
    """The newest review that gave a verdict on a tip other than this one, as its `commit_id`, `verdict` and `body`; None
    when no earlier tip was reviewed, or when this very tip already carries a verdict, UNREVIEWED included — a tip sent
    for review again is the queue's (its files changed on the default branch, or it overlaps what just merged), which
    reads the whole pull request against the new default branch. `VERDICT: UNREVIEWED` is never a reviewed tip: the
    model did not read it. With `usable`, the newest reviewed tip it accepts (an older one when the newest is not)."""
    if not head_sha:
        return None   # the head could not be read: nothing says which tips are earlier, so the review reads it whole
    best = None
    for rv in reviews or []:
        if rv.get("commit_id") == head_sha and _verdict(rv.get("body"), VERDICT_LINES + (VERDICT_UNREVIEWED,)):
            return None
        verdict = _verdict(rv.get("body"))
        if not verdict or not rv.get("commit_id") or rv.get("commit_id") == head_sha:
            continue
        if usable is not None and not usable(rv["commit_id"]):
            continue
        if best is None or (rv.get("submitted_at") or "") > (best.get("submitted_at") or ""):
            best = dict(rv, verdict=verdict)
    return best


def blocked_findings(prior):
    """What the earlier review blocked on: its BLOCKING lines; a BLOCKING review written before those lines existed gives
    its whole body; a CLEAN one blocked on nothing."""
    if prior.get("verdict") != "VERDICT: BLOCKING":
        return "(none — that review was CLEAN)"
    lines = [l.strip() for l in (prior.get("body") or "").splitlines()]
    marked = [l for l in lines if l.startswith(BLOCKING_MARK)]
    text = "\n".join(marked) if marked else "\n".join(l for l in lines if l and l not in VERDICT_LINES)
    return text[:PRIOR_FINDINGS_MAX]


def _pr_prompt(repo, gh_repo, head):
    # MANUAL ONLY (DESIGN.md §3): nothing triggers MODE=pr. Sessions open their own pull requests and the sweep opens
    # one for a branch left without one; a caller dispatching this checks first that no PR exists (git's API, never
    # the model), so the agent spends its tokens only on summarizing the diff.
    return (
        f"MODE=pr. Branch `{head}` on {gh_repo} has no open PR — this has ALREADY been verified "
        f"against the GitHub API by the caller, so do NOT spend a tool call re-checking it. The "
        f"repo is checked out at {repo}. Follow the `open-pr-for-branch` skill: find the default "
        f"branch, summarize what this branch changes against it from the actual diff, then open "
        f"the PR with `gh pr create --repo {gh_repo} --head {head}` giving it a real title and "
        f"body. Print the PR URL. End with DONE."
    )


def _harvest_prompt(repo, gh_repo):
    return (
        f"MODE=harvest. You are running your scheduled rule-harvest over your own past reviews "
        f"on {gh_repo}. The repo is checked out at {repo}. Follow the `harvest-rules-from-reviews` "
        f"skill EXACTLY: gather your recent posted reviews with gh, read your current rules, and "
        f"look for a RECURRING finding class (>=2 distinct reviews) not already covered. Either "
        f"(a) author ONE new rule-candidate file under "
        f"automation/cicd-reviewer/cicd_aios/.claude/rules/ on a cicd-rules/<slug> branch and "
        f"open a PR for it (the maintainer's merge is the approval gate — never approve or merge "
        f"it yourself), or (b) if nothing recurs or it is already covered, add nothing and say "
        f"so plainly. Your ONLY tool is bash: write the rule file with a quoted heredoc "
        f"(cat > path <<'EOF' ... EOF). Never call WriteBlockReportTool unless you are truly "
        f"blocked — it HALTS the run; it is not a progress note. End with DONE."
    )


def _coordinate_prompt(gh_repo, prs_json):
    return (
        f"MODE=coordinate. You are the MERGE COORDINATOR for {gh_repo}. Each of these open pull requests was reviewed "
        f"CLEAN on its own, and they touch overlapping files, so they cannot all merge without someone judging them "
        f"together: {prs_json}. Follow the `coordinate-merges` skill: read every one's diff with `gh pr diff <n> --repo "
        f"{gh_repo}`, decide the ORDER to merge them in and which (if any) must be HELD because it contradicts another, "
        f"undoes another, or would break combined with another — each hold with a one-sentence reason naming the other "
        f"pull request. Write ONLY the JSON {{\"order\": [numbers], \"hold\": [{{\"pr\": n, \"reason\": \"...\"}}]}} "
        f"to /out/decision.json with a quoted heredoc. You do not merge, push, comment or review. End with DONE."
    )


def build_agent():
    from heaven_base import BaseHeavenAgent, HeavenAgentConfig, UnifiedChat, ProviderEnum
    from heaven_base.memory.history import History
    from heaven_base.tools import BashTool

    config = HeavenAgentConfig(
        name="cicd_reviewer",
        system_prompt=BASE_SYSTEM_PROMPT,
        tools=[BashTool],
        provider=ProviderEnum.ANTHROPIC,
        model=os.environ.get("CICD_MODEL", "MiniMax-M3"),
        temperature=0.3,
        max_tokens=8000,
        use_uni_api=False,
        enable_compaction=True,
    )
    # max_tool_calls high enough for a real review loop (git diff, cat context, gh post).
    return BaseHeavenAgent(
        config, UnifiedChat, history=History(messages=[]), adk=False, max_tool_calls=ROUND_STEPS
    )


def extract_text(result):
    if not isinstance(result, dict):
        return str(result)
    if result.get("prepared_message"):
        return result["prepared_message"]
    hist = result.get("history")
    if hist is not None and getattr(hist, "messages", None):
        for msg in reversed(hist.messages):
            if msg.__class__.__name__ == "AIMessage" and getattr(msg, "content", None):
                return msg.content if isinstance(msg.content, str) else str(msg.content)
    return ""


VERDICT_LINES = ("VERDICT: CLEAN", "VERDICT: BLOCKING")


def _agrees(body):
    """A review's verdict line and its finding lines agree: a BLOCKING line stands only under `VERDICT: BLOCKING`."""
    lines = [l.strip() for l in (body or "").strip().splitlines() if l.strip()]
    if not lines or lines[-1] not in VERDICT_LINES:
        return False
    return lines[-1] == "VERDICT: BLOCKING" or not any(l.startswith(BLOCKING_MARK) for l in lines)


def verdict_posted(reviews, head_sha, since_iso):
    """True when a review on exactly this tip, posted since the run began, ends in a verdict line that its finding lines
    agree with. The deliverable is checked on GitHub, never inferred from the agent's last words; a review whose lines
    disagree is no result, and the run is tried again."""
    for rv in reviews or []:
        if rv.get("commit_id") != head_sha or (rv.get("submitted_at") or "") < since_iso:
            continue
        if _agrees(rv.get("body")):
            return True
    return False


def _head(gh_repo, pr):
    import subprocess
    return subprocess.run(["gh", "pr", "view", str(pr), "--repo", gh_repo, "--json", "headRefOid", "-q", ".headRefOid"],
                          capture_output=True, text=True).stdout.strip()


def _reviews(gh_repo, pr):
    import json
    import subprocess
    out = subprocess.run(["gh", "api", f"repos/{gh_repo}/pulls/{pr}/reviews", "--paginate", "--jq",
                          ".[] | {commit_id, submitted_at, body}"], capture_output=True, text=True).stdout
    return [json.loads(l) for l in out.splitlines() if l.strip()]


def _review_landed(gh_repo, pr, since_iso):
    return verdict_posted(_reviews(gh_repo, pr), _head(gh_repo, pr), since_iso)


def _git(repo, *args):
    import subprocess
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def prior_tip(repo, gh_repo, pr, base, git=None):
    """The last reviewed tip this review reads on from, or None for a whole review. A reviewed tip is read on from only
    when it is an ancestor of the checked-out head AND no merge of the default branch came in since it (both have the
    same merge base with `origin/<base>`): then `git diff <tip> HEAD` is the pull request's own change and nothing
    else, renames and deletions included. Otherwise — no reviewed tip, a rewritten history, the default branch merged
    in, a head or a merge base that cannot be read — the whole pull request is read."""
    git = git or (lambda *a: _git(repo, *a))
    rc, mb_head = git("merge-base", f"origin/{base}", "HEAD")
    if rc != 0 or not mb_head:
        return None

    def usable(sha):
        if git("merge-base", "--is-ancestor", sha, "HEAD")[0] != 0:
            return False
        rc, mb = git("merge-base", f"origin/{base}", sha)
        return rc == 0 and mb == mb_head
    return last_reviewed(_reviews(gh_repo, pr), _head(gh_repo, pr), usable)


def late_verdict_posted(comments, since_iso):
    """True when a comment posted since the run began ends in a verdict line — the late review's deliverable."""
    for c in comments or []:
        if (c.get("created_at") or "") < since_iso:
            continue
        if _agrees(c.get("body")):
            return True
    return False


def _late_review_landed(gh_repo, pr, since_iso):
    import json
    import subprocess
    out = subprocess.run(["gh", "api", f"repos/{gh_repo}/issues/{pr}/comments", "--paginate", "--jq",
                          ".[] | {created_at, body}"], capture_output=True, text=True).stdout
    return late_verdict_posted([json.loads(l) for l in out.splitlines() if l.strip()], since_iso)


def _coordinate_done() -> bool:
    import json
    try:
        with open("/out/decision.json") as f:
            return isinstance(json.load(f), dict)
    except (OSError, ValueError):
        return False


def _pr_opened(gh_repo, head) -> bool:
    import subprocess
    out = subprocess.run(["gh", "pr", "list", "--repo", gh_repo, "--head", head, "--state", "open", "--json", "number",
                          "-q", "length"], capture_output=True, text=True).stdout.strip()
    return out not in ("", "0")


def result_exists(mode, text, gh_repo, started) -> bool:
    """Whether the mode's RESULT is real — checked in the world, never read off the agent's last words (except the
    harvest, whose result may rightly be nothing)."""
    if mode == "review":
        return _review_landed(gh_repo, os.environ.get("PR_NUMBER", ""), started)
    if mode == "review-merged":
        return _late_review_landed(gh_repo, os.environ.get("PR_NUMBER", ""), started)
    if mode == "coordinate":
        return _coordinate_done()
    if mode == "pr":
        return _pr_opened(gh_repo, os.environ.get("HEAD_REF", ""))
    return "done" in (text or "").lower()


def agent_mode(goal: str) -> str:
    """Heaven's agent-mode command: the goal, run for up to ITERATIONS rounds (baseheavenagent._detect_agent_command)."""
    return f"agent goal={goal}, iterations={ITERATIONS}"


def main():
    mode = os.environ.get("MODE", "").strip().lower()
    repo = os.environ.get("REPO_DIR", "/repo")
    gh_repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not os.environ.get("MINIMAX_API_KEY"):
        sys.exit("FATAL: MINIMAX_API_KEY is not set — the review agent has no model credential.")

    if mode == "review":
        pr = os.environ.get("PR_NUMBER", "")
        prior = prior_tip(repo, gh_repo, pr, os.environ.get("BASE_REF", "") or "main")
        log.info("review of %s", f"what changed since {prior['commit_id'][:10]}" if prior else "the whole pull request")
        prompt = _review_prompt(
            repo, gh_repo, pr, os.environ.get("BASE_REF", ""), os.environ.get("HEAD_REF", ""), prior,
        )
    elif mode == "review-merged":
        prompt = _late_review_prompt(gh_repo, os.environ.get("PR_NUMBER", ""))
    elif mode == "pr":
        prompt = _pr_prompt(repo, gh_repo, os.environ.get("HEAD_REF", ""))
    elif mode == "harvest":
        prompt = _harvest_prompt(repo, gh_repo)
    elif mode == "coordinate":
        prompt = _coordinate_prompt(gh_repo, os.environ.get("COORD_INPUT", "[]"))
    else:
        sys.exit(f"FATAL: MODE must be 'review', 'review-merged', 'pr', 'harvest' or 'coordinate', got {mode!r}")

    log.info("mode=%s repo=%s gh_repo=%s model=%s cwd=%s",
             mode, repo, gh_repo, os.environ.get("CICD_MODEL", "MiniMax-M3"), os.getcwd())
    from datetime import datetime, timezone
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    agent = build_agent()
    log.info("agent built; agent mode, up to %d rounds of %d steps", ITERATIONS, ROUND_STEPS)
    result = asyncio.run(agent.run(prompt=agent_mode(prompt)))
    text = extract_text(result)
    print("=== CICD Reviewer output ===")
    print(text)
    if not result_exists(mode, text, gh_repo, started):
        # THE RESULT IS CHECKED IN THE WORLD — a verdict on the PR, the decision file, the opened PR — never read off
        # the agent's last words. Missing ⇒ the run failed, and the workflow tries once more.
        log.error("the run ended without its result — incomplete")
        sys.exit(f"FATAL: the {mode} run ended without its result.")
    log.info("run complete")


if __name__ == "__main__":
    main()
