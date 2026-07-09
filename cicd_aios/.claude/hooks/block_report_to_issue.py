"""ON_BLOCK_REPORT hook — turn a CICD reviewer's voluntary halt into a GitHub issue.

Auto-registered by heaven's devdir hook-loader: this file lives in the reviewer AIOS at
`cicd_aios/.claude/hooks/`, which is on the agent's cwd chain (the container WORKDIR/entrypoint is
`/cicd_aios`), so `resolve_devdirs` → `_register_devdir_hook_file` picks it up via the `register(registry)`
contract.

When the reviewer writes a block report (`create_block_report` fires `HookPoint.ON_BLOCK_REPORT` with the
rendered markdown), this opens a GitHub issue with that report pasted — so a blocked review becomes a
triageable backlog item on the monorepo instead of vanishing into the CI log.

Target repo = env `BLOCK_REPORT_ISSUE_REPO` if set, else `GITHUB_REPOSITORY`. Requires `gh` + a token with
`issues:write` in the container (the review/pr workflows grant it). Best-effort: never raises, and only
LOGS (never prints) so a failure is recoverable but never breaks the agent run.
"""
import logging
import os
import shutil
import subprocess

from heaven_base.baseheavenagent import HookPoint

logger = logging.getLogger(__name__)


def _open_block_report_issue(ctx) -> None:
    try:
        repo = os.environ.get("BLOCK_REPORT_ISSUE_REPO") or os.environ.get("GITHUB_REPOSITORY")
        if not repo:
            logger.warning("[block_report_to_issue] no BLOCK_REPORT_ISSUE_REPO/GITHUB_REPOSITORY — skipped")
            return
        if not shutil.which("gh"):
            logger.warning("[block_report_to_issue] gh not on PATH — skipped")
            return
        if not (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")):
            logger.warning("[block_report_to_issue] no GH_TOKEN/GITHUB_TOKEN — skipped")
            return

        md = (getattr(ctx, "data", {}) or {}).get("block_report_md") or "(no block report body was produced)"
        pr = os.environ.get("PR_NUMBER", "").strip()
        where = f"PR #{pr}" if pr else (os.environ.get("HEAD_REF", "").strip() or "a run")
        title = f"CICD reviewer blocked on {where}"
        body = (
            f"The CICD reviewer **voluntarily halted** (block report) while working on {where} "
            f"in `{os.environ.get('GITHUB_REPOSITORY', '?')}`.\n\n"
            f"It could not complete and deliberately did NOT fabricate output — this is an automated "
            f"triage item for a human to resolve.\n\n---\n\n{md}"
        )
        result = subprocess.run(
            ["gh", "issue", "create", "--repo", repo, "--title", title, "--body", body],
            check=False, capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            logger.info("[block_report_to_issue] opened block-report issue on %s: %s",
                        repo, (result.stdout or "").strip())
        else:
            logger.error("[block_report_to_issue] gh issue create failed (rc=%s): %s",
                         result.returncode, (result.stderr or "").strip())
    except Exception:
        logger.exception("[block_report_to_issue] failed (non-fatal — the agent run is unaffected)")


def register(registry) -> None:
    """Devdir hook-loader entrypoint (Form B): wire the ON_BLOCK_REPORT handler."""
    registry.register(HookPoint.ON_BLOCK_REPORT, _open_block_report_issue)
