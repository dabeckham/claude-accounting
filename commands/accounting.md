---
description: Usage & cost report from the local time-tracking ledger (time, tokens, cost, effort)
argument-hint: [today|week|month|all|N] [--billing]
allowed-tools: Bash
---

Run the accounting report:

`python ~/.claude/timelog-report.py $ARGUMENTS`

(No period given → it defaults to the last week.)

Show the script's output, then optionally add 1–3 short highlights drawn ONLY from
the printed numbers (e.g. biggest cost day, interactive hours, agent-time vs your
idle split, effort mix). Never state a number the script didn't print. Cost is
reference value under a subscription login — mention that only if relevant.
