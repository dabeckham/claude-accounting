# Time-Tracking Ledger

A cross-session, cross-project record of (a) how long Don spends in interactive
Claude sessions and (b) how long Claude's tasks take. Built 2026-06-17 so any
session can append, and a future UI can read it and generate reports.

## Files
- `timelog.jsonl` — the ledger. **Append-only, one JSON object per line.** Never
  rewrite or reorder; only append. Single-line appends are atomic, so parallel
  sessions are safe.
- `~/.claude/timelog.sh` — helper for agents to log intervals/events + view.
- `~/.claude/timelog-hook.sh` — hook-side logger (writes automatic events).
- Hooks are wired in `~/.claude/settings.json` (SessionStart, UserPromptSubmit, Stop).

## Two layers
1. **Automatic (hooks)** — captures the interactive timeline with no effort:
   - `session_start` event on every startup/resume/compact.
   - `prompt` event when Don submits a message (he becomes active; an agent turn begins).
   - `turn_end` event when the agent finishes a turn (waiting-on-Don begins).
   From consecutive events a report derives: agent turn time = `turn_end - prompt`;
   Don turnaround/idle = next `prompt - turn_end`; session span from `session_start`.
2. **Semantic (agent-logged intervals)** — richer task detail the hooks can't know:
   the agent captures a start with `timelog.sh now`, does the work, then logs
   `timelog.sh interval <category> <start> now "<desc>"`.

## Schema (timelog.jsonl)
Every line has: `kind`, `epoch`, `ts` (ISO8601 w/ tz offset), `category`,
`session`, `project`, `desc`.

- **event**: `{kind:"event", epoch, ts, category, session, project, desc}`
  - category ∈ `session_start | prompt | turn_end`
  - **`prompt` events** may carry `effort` (low/medium/high/extra/max/ultracode) +
    `effort_certain` (bool) when Don writes `effort: <level>` in the message — the
    only reliable way to capture the reasoning-effort selection (it can't be read
    from the API call or disk). A tag → `effort` + `effort_certain:true` (and is
    remembered in `~/.claude/.timelog-last-effort`); an untagged message inherits
    the last tagged level with `effort_certain:false` (assumed). No tag + no prior →
    no `effort` field. In reporting, treat uncertain as accurate but distinguishable.
  - **`turn_end` events also carry per-turn accountability fields**, parsed from
    the transcript tail by `timelog-hook.py`: `model` (e.g. claude-opus-4-8),
    `in_tokens`, `out_tokens`, `cache_read`, `cache_write_5m`, `cache_write_1h`
    (cache writes split by TTL — they bill at different rates), `web_search`,
    `web_fetch`, `used_thinking` (bool), `msgs` (assistant messages in the turn).
    Token usage + model are NOT hook fields — they live only in the transcript,
    so the Stop hook reads it. The token sums cover every API call in the turn
    (each tool round-trip is billed), so `cache_read` can be large.

### Cost
`sh ~/.claude/timelog.sh cost [today|all|N]` prices the `turn_end` rows from
`~/.claude/time-tracking/pricing.json` (USD per 1M tokens, per model). Cost is
computed at **report time** from that table — not stored per row — so correcting
or updating a rate re-prices history correctly. Cache multipliers are the
Anthropic standard: write-5m = 1.25× input, write-1h = 2× input, read = 0.1×
input. Update base rates from https://platform.claude.com/docs/en/pricing .
- **interval**: adds `start_epoch, start_ts, end_epoch, end_ts, dur_s`
  (`epoch`/`ts` = end). category ∈ `thinking | coding | deploy | research |
  review | waiting | meeting | other`.

### What is NOT capturable
- **Reasoning/effort level** (fast mode, effort selection) is not recorded
  anywhere in the transcript, so it can't be logged. `model` + `used_thinking`
  are the only persisted proxies.
- Hooks only fire inside **Claude Code** on this machine. They do NOT see
  claude.ai web, the Claude desktop/mobile chat apps, or raw Anthropic API
  usage. For all-surface, account-wide token/billing totals, the authoritative
  source is the Anthropic Console usage/billing (or the Admin usage API).

`session` = first 8 chars of the Claude session id (hook events) or "cli"
(agent-logged). `project` = basename of the working directory.

## Conventions for categories
- `thinking` — planning, designing, reading code to understand, diagnosing.
- `coding` — writing/editing code, configs, docs.
- `deploy` — building images, deploying, reprocessing, infra ops.
- `research` — web/docs lookups, investigating an external system.
- `review` — reviewing diffs/PRs.
- `waiting` — blocked on Don (agent-logged when it explicitly waits).
- `meeting` / `other` — catch-alls.

## Quick views
- `sh ~/.claude/timelog.sh view 30` — last 30 entries + interval totals.
- `sh ~/.claude/timelog.sh today` — today's entries + per-category totals.
- Raw report later: read `timelog.jsonl`, pair `prompt`→`turn_end` per session
  for agent turn durations, and `turn_end`→next `prompt` for Don idle gaps.
