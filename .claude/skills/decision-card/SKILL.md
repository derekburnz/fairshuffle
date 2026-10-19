---
name: decision-card
description: Formats any choice for Derek as a short Decision Card (options, pros, cons, effort, recommendation) and then stops to wait for his answer. Use whenever there is more than one reasonable way forward, a do-it-or-skip-it choice, a new dependency or tool to add or a "what should we work on next" moment.
---

# Decision Card

Derek makes every decision in this project. Your job is to make each decision fast and easy for him.

## Steps

1. Check `docs/planning/DECISIONS.md`. If a pre-written card exists for this decision (D1 to D17), start from it and refresh any facts that changed.
2. Write the card using the template below. Keep it readable in under 30 seconds: at most 4 options, one line per cell.
3. If the AskUserQuestion tool is available, use it with the options as choices (recommended option first, labelled "(Recommended)"). Otherwise post the card as text.
4. Stop and wait. Do not continue the work that depends on this choice.
5. When Derek answers, log it in the Decision log table in `docs/planning/DECISIONS.md`: ID, choice, today's date, his reason or yours in one line.
6. If the answer affects other parts of the plan, say in one or two lines what will change.

## Template

```
DECISION D#: <short title>
Why it matters: <one sentence>

| Option | Pros | Cons | Effort |
|--------|------|------|--------|
| A. ... | ...  | ...  | Low    |
| B. ... | ...  | ...  | Medium |

Recommendation: <option>, because <one line>.
Reply with A or B (or "explain more").
```

For a new decision not in DECISIONS.md, give it the next free ID.

## "What's next?" variant

Use when a task or phase is done and more than one next step is valid:

```
WHAT'S NEXT?
Done: <one line>

| Option | What it gets you | Effort |
|--------|------------------|--------|
| A. ... | ... | ... |
| B. ... | ... | ... |
| C. Stop here and write a status report | Clean pause point | Low |

Recommendation: <option>, because <one line>.
```

## Style

Plain words. No emojis. No em dashes or en dashes. No Oxford commas.
