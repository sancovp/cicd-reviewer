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
  MODE               review | pr | harvest | coordinate   (which task to run)
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

MAX_TOOL_CALLS = int(os.environ.get("CICD_MAX_TOOL_CALLS", "80"))
POST_BY = MAX_TOOL_CALLS - 10   # the review is posted by this call at the latest: an unposted review is worth nothing

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


def _review_prompt(repo, gh_repo, pr, base, head):
    return (
        f"MODE=review. Review pull request #{pr} on {gh_repo}: head `{head}` against base "
        f"`{base}`. The repo is checked out at {repo}. Follow the `review-pr-diff` skill: read "
        f"the diff, find real correctness/security/contract issues per your review-discipline "
        f"rule (cite path:line, trace each to an exact symptom, drop vague ones), and post your "
        f"review with `gh pr review {pr} --repo {gh_repo} --comment` — by your tool call {POST_BY} at the latest: "
        f"you have {MAX_TOOL_CALLS}, and a review you never post is worth nothing, so on a large pull request read "
        f"the diff and the riskiest files first, then post what you found. The review's LAST LINE must be "
        f"exactly `VERDICT: CLEAN` (no blocking finding) or `VERDICT: BLOCKING` (at least one real "
        f"correctness/security/contract finding) — the workflow merges the pull request on CLEAN. "
        f"End with DONE."
    )


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
        config, UnifiedChat, history=History(messages=[]), adk=False, max_tool_calls=MAX_TOOL_CALLS
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


def verdict_posted(reviews, head_sha, since_iso):
    """True when a review on exactly this tip, posted since the run began, ends in a verdict line. The deliverable is
    checked on GitHub, never inferred from the agent's last words."""
    for rv in reviews or []:
        if rv.get("commit_id") != head_sha or (rv.get("submitted_at") or "") < since_iso:
            continue
        lines = [l.strip() for l in (rv.get("body") or "").strip().splitlines() if l.strip()]
        if lines and lines[-1] in VERDICT_LINES:
            return True
    return False


def _review_landed(gh_repo, pr, since_iso):
    import json
    import subprocess
    head = subprocess.run(["gh", "pr", "view", str(pr), "--repo", gh_repo, "--json", "headRefOid", "-q", ".headRefOid"],
                          capture_output=True, text=True).stdout.strip()
    out = subprocess.run(["gh", "api", f"repos/{gh_repo}/pulls/{pr}/reviews", "--paginate", "--jq",
                          ".[] | {commit_id, submitted_at, body}"], capture_output=True, text=True).stdout
    reviews = [json.loads(l) for l in out.splitlines() if l.strip()]
    return verdict_posted(reviews, head, since_iso)


def main():
    mode = os.environ.get("MODE", "").strip().lower()
    repo = os.environ.get("REPO_DIR", "/repo")
    gh_repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not os.environ.get("MINIMAX_API_KEY"):
        sys.exit("FATAL: MINIMAX_API_KEY is not set — the review agent has no model credential.")

    if mode == "review":
        prompt = _review_prompt(
            repo, gh_repo, os.environ.get("PR_NUMBER", ""),
            os.environ.get("BASE_REF", ""), os.environ.get("HEAD_REF", ""),
        )
    elif mode == "pr":
        prompt = _pr_prompt(repo, gh_repo, os.environ.get("HEAD_REF", ""))
    elif mode == "harvest":
        prompt = _harvest_prompt(repo, gh_repo)
    elif mode == "coordinate":
        prompt = _coordinate_prompt(gh_repo, os.environ.get("COORD_INPUT", "[]"))
    else:
        sys.exit(f"FATAL: MODE must be 'review', 'pr', 'harvest' or 'coordinate', got {mode!r}")

    log.info("mode=%s repo=%s gh_repo=%s model=%s cwd=%s",
             mode, repo, gh_repo, os.environ.get("CICD_MODEL", "MiniMax-M3"), os.getcwd())
    from datetime import datetime, timezone
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    agent = build_agent()
    log.info("agent built; running review loop (max_tool_calls=%d)", MAX_TOOL_CALLS)
    result = asyncio.run(agent.run(prompt=prompt))
    text = extract_text(result)
    print("=== CICD Reviewer output ===")
    print(text)
    if mode == "review":
        # THE DELIVERABLE IS A POSTED VERDICT. A run whose review never reached the pull request (a shell error while
        # posting, a model that gave up) is a failure whatever the agent said, so the workflow tries again.
        if not _review_landed(gh_repo, os.environ.get("PR_NUMBER", ""), started):
            log.error("no review with a verdict line reached the pull request's tip — run incomplete")
            sys.exit("FATAL: no verdict was posted on the pull request's tip.")
    elif "done" not in (text or "").lower():
        # The agent did not signal completion — surface as failure so CI is not silently green.
        log.error("agent did not emit DONE — run incomplete")
        sys.exit("FATAL: agent did not emit DONE — treating run as incomplete.")
    log.info("review run complete")


if __name__ == "__main__":
    main()
