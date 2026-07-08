# Git Safety — Never Destroy, Never Leak

You have `git` and `gh` via bash on a real repo at `/repo`. Hard limits:

- **Never force-push.** No `git push --force` / `-f`, ever.
- **Never push to the default branch directly.** Changes go through a branch + PR.
- **Never delete branches you did not create**, and never delete the default branch.
- **Never commit secrets.** If you see a credential in the diff, that IS a finding —
  flag it, do not "fix" it by rewriting history.
- **Branch first when opening a PR** (`MODE=pr`): create `cicd/<short-desc>` off the
  pushed branch's HEAD; commit only if you have a real change to add; push that branch,
  then `gh pr create`.
- **In `MODE=review` you do not modify code** — you read the diff and post a review. Do
  not push commits, do not open PRs, do not edit files in `/repo`.
- Always operate with an explicit path (`git -C /repo`, `gh` with `--repo $GITHUB_REPOSITORY`),
  never by cd-ing your own process into `/repo`.

If an operation would violate one of these, stop and report it as a blocker in your
output instead of doing it.
