"""Claude Code PostToolUse hook: format and lint a Python file right after Claude edits it.

PROPOSED in Stage C (D23). Inert until copied to /.claude/hooks/ in Phase 0.

Claude Code runs this after every Edit or Write and passes the tool call as JSON on
stdin. If the edited file is a .py file inside the project, the hook runs
`ruff check --fix` and then `ruff format` on that one file. Any lint problem ruff
cannot fix by itself is printed to stderr with exit code 2, which Claude Code shows
to Claude so it can fix the problem straight away. Nothing is ever blocked: the
edit has already happened.

Uses only the standard library plus ruff from the project's dev dependencies.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0  # not our input; never break Claude's session over a hook

    file_path = event.get("tool_input", {}).get("file_path", "")
    if not file_path.endswith(".py"):
        return 0

    project = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")).resolve()
    target = Path(file_path).resolve()
    if project not in target.parents or not target.exists():
        return 0  # only touch files inside this project

    if importlib.util.find_spec("ruff") is None:
        return 0  # dev dependencies not installed yet (before P1-01); nothing to run

    # S603 (untrusted subprocess input) does not apply: the command is this Python's ruff,
    # the path was checked above to be inside the project, and no shell is involved.
    ruff = [sys.executable, "-m", "ruff"]
    lint = subprocess.run(  # noqa: S603
        [*ruff, "check", "--fix", "--quiet", str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    subprocess.run([*ruff, "format", "--quiet", str(target)], check=False)  # noqa: S603
    if lint.returncode != 0:
        print(f"ruff found problems it could not auto-fix in {target.name}:", file=sys.stderr)
        print(lint.stdout.strip() or lint.stderr.strip(), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
