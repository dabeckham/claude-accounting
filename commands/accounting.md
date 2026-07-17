---
description: Usage & cost report from the local sessions ledger (time, tokens, cost, effort)
argument-hint: [today|week|month|all|N] [--billing]
allowed-tools: Bash
---

Run the accounting report over the **sessions ledger** (`~/.claude/time-tracking/timelog.jsonl`,
the hook-written per-turn ledger):

`python ~/.claude/timelog-report.py $ARGUMENTS`

(No period given → it defaults to the last week.)

Show the script's output, then optionally add 1–3 short highlights drawn ONLY from
the printed numbers (e.g. biggest cost day, interactive hours, agent-time vs your
idle split, effort mix). Never state a number the script didn't print. Cost is
reference value under a subscription login — mention that only if relevant.

**Accuracy caveat (until the historical cleanup runs):** turns are counted deduped by
`requestId` as of 2026-07-17, so rows written from that date forward are correct. Rows
written *before* that date were inflated ~2.6× by a streaming over-count, so `week`/
`month`/`all` windows that reach into pre-fix history overstate tokens and cost. `today`
and recent-day windows are clean. Flag this if a report spans the boundary.
