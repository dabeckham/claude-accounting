# Cost — how the dollar figure is derived

Cost is **computed at report time** from the token counts already on each `turn_end` row, multiplied by a per‑model rate table in [`config/pricing.json`](../config/pricing.json). Nothing is stored per row, so correcting or updating a rate automatically re‑prices all history.

## Formula

For each `turn_end` row, using the rates for that row's `model` (USD per 1,000,000 tokens):

```
cost = ( in_tokens       × input
       + out_tokens      × output
       + cache_read      × cache_read
       + cache_write_5m  × cache_write_5m
       + cache_write_1h  × cache_write_1h ) ÷ 1,000,000
```

## Rate table

`pricing.json` holds base input/output rates per model plus the three cache rates. The cache rates are the standard Anthropic multipliers of the input rate:

| Component | Rate |
|---|---|
| cache write, 5‑minute TTL | **1.25× input** |
| cache write, 1‑hour TTL | **2× input** |
| cache read | **0.1× input** |

Example base rates (per 1M tokens; cached 2026‑05‑26 — **verify current values** at <https://platform.claude.com/docs/en/pricing>):

| Model | input | output | cache write 5m / 1h | cache read |
|---|---|---|---|---|
| `claude-opus-4-8` | $5 | $25 | $6.25 / $10 | $0.50 |
| `claude-sonnet-4-6` | $3 | $15 | $3.75 / $6 | $0.30 |
| `claude-haiku-4-5` | $1 | $5 | $1.25 / $2 | $0.10 |

An unknown model falls back to the `default` block in `pricing.json`.

## Why cache writes are split by TTL

Claude Code uses prompt caching heavily, and a cache write at the 1‑hour TTL costs **2×** input vs **1.25×** for the 5‑minute TTL. The transcript reports the two buckets separately (`cache_creation.ephemeral_5m_input_tokens` / `ephemeral_1h_input_tokens`), so the hook records them separately and the cost formula prices each correctly. (Claude Code's own writes are typically 1‑hour.)

## A note on magnitude

On long agentic sessions, **`cache_read` dominates** the cost — the full context is re‑read on every tool round‑trip. A single heavy turn can be several dollars even though the visible output is small. That's accurate to how the API bills, and it's exactly the accountability signal this project exists to surface.

## Usage

```sh
sh ~/.claude/timelog.sh cost today    # priced turns today + totals by model/project
sh ~/.claude/timelog.sh cost all      # all priced turns
sh ~/.claude/timelog.sh cost 30       # last 30 priced turns
```
