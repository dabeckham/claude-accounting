---
name: accounting
description: Generate a usage/accounting report from the local Claude Code time-tracking ledger — interactive hours, agent working time, task intervals, token usage, cost (Actual locked-in + present-day), and reasoning-effort mix. Use when the user runs /accounting or asks for a time/cost/usage report of their Claude Code sessions.
---

# /accounting — usage & cost report

Print a deterministic report computed from the local ledger
(`~/.claude/time-tracking/timelog.jsonl`). The numbers come from the script, not
from you — do not invent or recompute them.

## How to run

```
python ~/.claude/skills/accounting/report.py [period] [--billing]
```

- **period**: `today` · `week` (default) · `month` · `all` · or an integer = last N days.
- **--billing**: also print the billing-channel note (subscription vs api_key). Off by default.

Map the user's request to the period:
- "today" → `today`; "this week" / no period → `week`; "this month" → `month`;
  "everything" / "all time" → `all`; "last 10 days" → `10`.
- If they ask about billing / "is this real money" → add `--billing`.

## Presenting the result

1. Run the script and show its output verbatim (it's already formatted).
2. Optionally add **1–3 sentences** of plain-language highlights drawn ONLY from
   the printed numbers — e.g. the biggest cost day, total interactive hours,
   agent-time vs your-idle-time split, or the effort mix. Never state a number
   the script didn't print.

## Notes
- Cost is **reference value** under a subscription login (API-equivalent, not money
  billed) — say so if asked; the true bill lives in the Anthropic Console.
- Source + design: github.com/dabeckham/claude-accounting (the `report.py` here is
  the same file shipped under `skills/accounting/` in that repo).
