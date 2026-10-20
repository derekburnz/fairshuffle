---
name: ship-change
description: "Runs this project's workplace Git workflow for a finished change (tests, security review, Conventional Commit, push, pull request linked to its issue) and then squash-merges it once CI is green and the security review passes. Use when a task is complete and ready to commit, or when Derek says ship it, commit this or open a PR."
---

# Ship a change

Follow every step. Stop and ask Derek wherever marked ASK.

1. **Branch check.** Confirm you are on a feature branch (`feat/<issue#>-<name>`, `fix/...`, `docs/...`, `test/...`, `chore/...`, `ci/...`), not `main`. If on `main`, create the right branch first.
2. **Tests.** Run the full test suite and the linter. If anything fails, fix it or report it. Do not continue with failures.
3. **Diff review.** Show Derek a short summary of what changed (files and one line each).
4. **Security review.** Stage the changes and ask the `security-reviewer` agent to review the staged diff. On FAIL, fix the findings and repeat. Never skip this for auth, config, logging or networking changes.
5. **Commit.** Conventional Commit message: `type(scope): short summary` plus a body explaining why. Reference the issue (`Refs #12`). The gitleaks pre-commit hook runs automatically; if it blocks the commit, stop and tell Derek what it found (location only, never the value).
6. **Push. ASK.** Tell Derek which branch you are pushing and wait for approval.
7. **Pull request.** Create a PR with `gh pr create` (or the GitHub connector) using `.github/pull_request_template.md`. Title matches the commit style. Body includes `Closes #<issue>`, what changed, how it was tested and screenshots for UI changes. Add labels and the milestone.
8. **CI.** Wait for checks. If they fail, fix on the same branch and push again (ask again before pushing).
9. **Merge.** When CI is green and the security review is PASS, squash merge (GitHub deletes the branch), then tell Derek: PR link, CI status, security review result (P0-21).
10. **Wrap up.** Switch back to `main` and pull. If this finished a milestone, run the `phase-report` skill.

Never force-push. Never commit to `main` directly. Never merge with failing checks or without a security review PASS.
