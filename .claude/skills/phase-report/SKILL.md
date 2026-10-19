---
name: phase-report
description: Writes a short end-of-phase or end-of-session report for Derek (what was built, what he can now explain, open issues, usage tips) and finishes with a "What's next?" Decision Card. Use when a milestone or phase is complete, when a work session is ending or when Derek asks for status.
---

# Phase report

Keep the whole report to one screen.

## Template

```
PHASE REPORT: <phase name> (<version tag if any>)

Built:
<2 to 4 lines, plain words, what now works>

You can now explain:
<1 to 3 concepts Derek learned this phase, one line each, interview-ready>

On GitHub:
<milestone progress, PRs merged, release or tag if any>

Open issues or risks:
<list or "none">

WHAT'S NEXT?
| Option | What it gets you | Effort |
|--------|------------------|--------|
| A. <next roadmap phase> | ... | ... |
| B. <alternative> | ... | ... |
| C. Stop here | Clean pause point | Low |

Recommendation: <option>, because <one line>.
```

## Also do

1. Update the "Current status" line at the bottom of `CLAUDE.md`.
2. Make sure every decision made this phase is in the log in `docs/planning/DECISIONS.md`.
3. Suggest `/clear` before starting the next phase to save usage (CLAUDE.md and the plan files bring the next session up to speed).
4. Wait for Derek's choice.

Style: no emojis, no em dashes or en dashes, no Oxford commas.
