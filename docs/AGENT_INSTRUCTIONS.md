# Agent instructions (cross‑session)

For the **agent‑logged interval** layer and the **effort tag** to be used consistently, add an instruction to your global `~/.claude/CLAUDE.md` (loads in every project). Drop in the snippet below.

```markdown
## ⏱️ Time tracking — log work + the user's interactive hours

There is ONE global append-only ledger: `~/.claude/time-tracking/timelog.jsonl`.

**Automatic (already wired — do not duplicate):** global hooks in
`~/.claude/settings.json` log `session_start`, `prompt`, and `turn_end` events
(via `~/.claude/timelog-hook.sh`). `turn_end` also records the turn's model +
token usage (in/out/cache_read/cache_write_5m/cache_write_1h/web_search/
web_fetch/used_thinking/msgs), parsed from the transcript tail.

**Your job — log task-level intervals as you work.** At natural boundaries
(finishing a sub-task, switching activity, before a long wait) bracket the work:
  START=$(sh ~/.claude/timelog.sh now)
  # …do the work…
  sh ~/.claude/timelog.sh interval <category> "$START" now "<brief description>"
Categories: thinking | coding | deploy | research | review | waiting | meeting | other.
Log a handful of intervals per task, NOT every tool call. Estimate + note "(est.)"
if you missed a start.

**Effort:** the user captures reasoning effort in-band by writing `effort: <level>`
in a message (low|medium|high|extra|max|ultracode). The prompt hook stamps it and
carries it forward (uncertain) on untagged turns. Don't try to auto-detect it — it
isn't readable from the API call or disk (see the project's docs/EFFORT.md).

Views: `sh ~/.claude/timelog.sh today` | `view [N]` | `cost [today|all|N]`.
```

That's the entire behavioral contract. The hooks handle the automatic layer with no agent involvement; this snippet covers the two things only the agent (or user) can do — categorize work and tag effort.
