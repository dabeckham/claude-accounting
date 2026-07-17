# Backfilling the ledger from historical transcripts

The hooks only log from when they were installed (2026-06-17 on the dev machine),
so earlier days are blank and `week`/`month`/`all` reports start empty before that.
But Claude Code keeps full per-message transcripts under
`~/.claude/projects/**/*.jsonl` reaching weeks further back, and every `assistant`
line carries the model + token usage needed to rebuild a turn.
`scripts/backfill-from-transcripts.py` replays those transcripts and appends one
reconstructed `turn_end` per turn.

## Counting: dedupe by `requestId`

Transcripts contain **streaming snapshots**: a single API response is written as
several assistant records that share one `requestId` (and one `message.id`), each
repeating the same `usage`. Counting every record multi‑counts the real API calls —
measured **~2.6× on current transcripts** (e.g. 63 records → 29 real calls).

The summer therefore **dedupes by `requestId`**, keeping the last snapshot per
request and counting it once. On a full transcript this lands on 326,617 output tokens
across 252 calls, versus 873,552 (2.67×) if every record is summed.

> **Correction (2026-07-17).** Earlier revisions summed **every** record (via each
> message's `usage.iterations` array) on the theory that it "already collapsed the
> snapshots." It does not — it counts each duplicate record, inflating every streamed
> turn ~2.6×. The bug went unnoticed because the backfill's verify gate reconciled the
> reconstruction against the **live hook**, which summed the same way — a circular
> check that reproduced the inflation instead of catching it. An independent
> per-`requestId` recount of the same transcripts exposed it. `summarize_turn` now
> dedupes; historical ledger rows written before this date are still inflated (see the
> verify gate below).

## The fix: one shared summer

The turn-boundary + accumulation + pricing logic lives in **`timelog_core.py`**, which
**both** the live hook (`timelog-hook.py`) and the backfill import. So a reconstructed
turn is counted byte-for-byte the way the hook counts it live — there is only one code
path, and it can't drift.

- `iter_turn_slices(rows)` — split a transcript into turns at each prompt boundary.
- `summarize_turn(rows)` — sum one turn's assistant usage, deduped by `requestId`.
- `price_turn(rec, schedules, date_str)` — cost from the schedule in effect on a date.

## The verify gate

Before trusting any reconstruction, run:

```sh
python ~/.claude/backfill-from-transcripts.py --verify
```

It re-derives the turns the live hook **already recorded** (matching by session +
end-time) and compares tokens and `cost_usd`.

> ⚠️ **Since the 2026-07-17 dedupe fix, `--verify` intentionally MISMATCHES historical
> rows.** Rows written by the pre-fix hook are inflated ~2.6×; the fixed summer
> reproduces the *correct* (lower) numbers, so the comparison now flags exactly how
> much each old turn was over-counted. That is the fix working, not a regression — the
> mismatch is the measure of the damage, and the input to the cleanup that re-derives
> the historical rows. Verify against a turn written *after* the fix to confirm a clean
> reproduction.

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
