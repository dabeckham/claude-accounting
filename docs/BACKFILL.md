# Backfilling the ledger from historical transcripts

The hooks only log from when they were installed (2026-06-17 on the dev machine),
so earlier days are blank and `week`/`month`/`all` reports start empty before that.
But Claude Code keeps full per-message transcripts under
`~/.claude/projects/**/*.jsonl` reaching weeks further back, and every `assistant`
line carries the model + token usage needed to rebuild a turn.
`scripts/backfill-from-transcripts.py` replays those transcripts and appends one
reconstructed `turn_end` per turn.

## Why a naive reconstruction is wrong

The obvious approach — sum `message.usage` over every assistant line — does **not**
reconcile with the ledger, because transcripts contain **streaming snapshots**: the
same `message.id` appears many times as the response streams. For 2026-06-17, 1,056
raw assistant lines collapse to 401 unique ids.

- Counting every line (no dedup) **overcounts** (cost $338.90 vs the ledger's $138.90).
- Deduping by `message.id` (first / last / max — all equivalent) **undercounts** ($130.09).
- A token-level diff is **bidirectional** (some fields high, some low), proving it's
  the *summing method*, not a dedup tweak.

The live hook doesn't sum per message — it sums **per turn**. It finds the turn
boundary at the last real user prompt (`type == "user"` **without** a `toolUseResult`
key) and accumulates the `usage` of the assistant messages since then, preferring
each message's `usage.iterations` array (which already collapses the snapshots).

## The fix: one shared summer

The turn-boundary + accumulation + pricing logic lives in **`timelog_core.py`**, which
**both** the live hook (`timelog-hook.py`) and the backfill import. So a reconstructed
turn is counted byte-for-byte the way the hook counts it live — there is only one code
path, and it can't drift.

- `iter_turn_slices(rows)` — split a transcript into turns at each prompt boundary.
- `summarize_turn(rows)` — sum one turn's assistant usage (the hook's old `_accum`).
- `price_turn(rec, schedules, date_str)` — cost from the schedule in effect on a date.

## The verify gate

Before trusting any reconstruction, run:

```sh
python ~/.claude/backfill-from-transcripts.py --verify
```

It re-derives the turns the live hook **already recorded** (matching by session +
end-time) and confirms they reproduce the ledger's tokens and `cost_usd` **to the
cent**. On the dev machine: 39/39 ledger turns matched, 38 reproduce exactly. The one
exception is the very first turn ever logged — written by a pre-`cache_write`-split
hook revision that stored a `cache_creation` field and didn't price the cache write;
it's reported explicitly and tolerated. Only reconstruct once this gate passes.

(`--verify` checks only real live-hook turns, ignoring any `reconstructed` rows, so it
stays meaningful and re-runnable after a backfill has been applied.)

## De-duplication: by local date

De-dup is by **local date**: any date that already has `turn_end` events in the ledger
is left **completely untouched**, so existing day totals never change and re-running
`--apply` is idempotent. The trade-off is that turns from *before* the hook went live
on an already-present date (the 06-17 morning, ~$200 of pre-install usage) are **not**
recovered — the conservative choice that guarantees no double counting. Recovering them
would change the 06-17 total and require a fuzzier per-turn matcher.

## Provenance & safety

- Every reconstructed row is stamped `reconstructed: true` and
  `source: "transcript-backfill"`.
- Each turn is priced with the schedule in effect **on the turn's own date**
  (not today), via the dated schedules in `pricing.json`.
- The turn's `ts`/`epoch`/day-bucket come from its **last assistant message**
  timestamp (UTC `Z` in the transcript) converted to **local** time, matching how the
  live Stop hook stamps `ts`.
- `--apply` writes a timestamped `timelog.jsonl.<ts>.bak` before appending.

## Usage

```sh
python ~/.claude/backfill-from-transcripts.py --verify     # gate (run first)
python ~/.claude/backfill-from-transcripts.py --dry-run    # per-day deltas, no writes (default)
python ~/.claude/backfill-from-transcripts.py --apply      # back up, then append
```
