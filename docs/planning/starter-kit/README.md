# Starter kit (PROPOSED, NOT ACTIVE)

Everything in this folder is a draft. None of it does anything until Derek approves it in Decision D7 and Claude copies it to the matching path at the project root in Phase 0. Files that stay here are inert, because Claude Code only loads agents, skills and settings from the root `.claude/` folder.

Tailored for Python and PySide6 in Stage C (2026-10-09). Originals are kept in the project's shared folder at `setup/stage-c/starter-kit-originals/`. Derek answered D18 to D24 on 2026-10-13 and every file here matches those answers. The hand-written `scripts/hooks/pre-commit` was replaced by `.pre-commit-config.yaml` (D23 C) and moved to `setup/stage-c/superseded-by-d23/` in the project folder.

| File here | Copy to | What it does | Stage C change |
|-----------|---------|--------------|----------------|
| `.gitignore` | `/.gitignore` | Keeps secrets, tokens, backups, logs and build output out of Git | Python section only; C# and Tauri sections removed |
| `.env.example` | `/.env.example` | Placeholder config; Derek copies it to `.env` and fills in the real Client ID himself | None |
| `.claude/settings.json` | `/.claude/settings.json` | Permission rules: deny `.env` and force-push, ask before push, merge, tag and release | Adds the formatter hook (PostToolUse on Edit and Write) |
| `.claude/hooks/format_python.py` | `/.claude/hooks/` | New. Runs `ruff check --fix` and `ruff format` on each Python file Claude edits; reports leftover problems back to Claude | New file (formatter hook approved in D7) |
| `.claude/agents/*.md` | `/.claude/agents/` | The five approved subagents | None |
| `.claude/skills/*/SKILL.md` | `/.claude/skills/` | The four approved skills | None |
| `.github/pull_request_template.md` | `/.github/` | PR checklist | None |
| `.github/ISSUE_TEMPLATE/*.md` | `/.github/ISSUE_TEMPLATE/` | Bug and feature templates | None |
| `.github/workflows/secret-scan.yml` | `/.github/workflows/` | gitleaks scan on PRs and `main` | None |
| `.github/workflows/ci.yml` | `/.github/workflows/` | New. Formatting, lint, type check and tests, all on Windows | New file (D18 to D20, D24); copied in Phase 1 (P1-02) |
| `pyproject.toml` | `/pyproject.toml` | New. Project metadata, dependencies and ruff, pyright and pytest settings | New file (D18 to D22); copied in Phase 1 (P1-01) |
| `.pre-commit-config.yaml` | `/.pre-commit-config.yaml` | New. The pre-commit framework runs gitleaks, ruff lint and format and small hygiene checks before every commit | Replaces `scripts/hooks/pre-commit` (D23 C) |

## Install notes for Claude

1. Walk Derek through each file in a sentence or two before copying it.
2. Verify at install time (these change): current uv, ruff and PySide6 versions, current gitleaks CLI syntax (the hook uses `gitleaks git --pre-commit --staged --redact`), current major versions of `actions/checkout`, `astral-sh/setup-uv` and `gitleaks/gitleaks-action` and the package ID used to install gitleaks on Windows.
3. `.claude/settings.json` must be strict JSON (no comments, no trailing commas). Run `claude doctor` after copying to validate it.
4. The rules cover both the Bash tool (Git for Windows installed) and the PowerShell tool. Keep both sets.
5. After copying `.pre-commit-config.yaml` and running `uv sync`: `uv run pre-commit install`. Do not set `core.hooksPath`; pre-commit refuses to install while it is set. The first commit takes a few minutes while pre-commit builds the hook environments.
6. After Phase 0, delete this starter-kit folder (ask Derek first) so there is only one copy of each file.
