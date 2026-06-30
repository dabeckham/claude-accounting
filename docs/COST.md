# Cost — locked-in actual vs present-day value

Each turn's dollar cost is **locked in at the prices in effect when it ran**, so a later price change never rewrites history. Reports show two columns:

- **Actual** — what the turn cost under the pricing schedule in effect that day (stamped on the row as `cost_usd`).
- **Today** — the same tokens re-priced at the *current* schedule (computed at report time).

## Dated pricing schedules

[`config/pricing.json`](../config/pricing.json) holds a list of **schedules**, each with an `effective_from` date:

```jsonc
{
  "schedules": [
    {
      "effective_from": "2026-05-26",
      "models": { "claude-opus-4-8": { "input": 5.0, "output": 25.0,
                  "cache_write_5m": 6.25, "cache_write_1h": 10.0, "cache_read": 0.50 }, ... },
      "default": { ... }
    }
  ]
}
```

The schedule applied to a turn is the **latest one whose `effective_from` ≤ the turn's date**. When Anthropic changes prices, **append a new schedule** with a later `effective_from` — never edit a past schedule except to correct an error. Old turns keep their original rates; new turns use the new ones.

## How a turn is priced

The `Stop` hook computes and **stamps** `cost_usd` + `pricing_from` on each `turn_end` row using the schedule effective that day:

```
cost = ( in_tokens       × input
       + out_tokens      × output
       + cache_read      × cache_read
       + cache_write_5m  × cache_write_5m
       + cache_write_1h  × cache_write_1h ) ÷ 1,000,000
```

Cache rates are the standard Anthropic multipliers of the input rate: **write-5m = 1.25×**, **write-1h = 2×**, **read = 0.1×**. (Claude Code's own cache writes are typically 1-hour.)

Existing rows logged before cost stamping was added are **backfilled** from the schedule effective on their date.

## Reporting

```sh
sh ~/.claude/timelog.sh cost today          # today's turns: Actual + Today columns + totals
sh ~/.claude/timelog.sh cost all            # all priced turns
sh ~/.claude/timelog.sh cost 30             # last 30 priced turns
sh ~/.claude/timelog.sh cost all --billing  # also print the billing-channel note (off by default)
```

Actual and Today are equal until a second dated schedule exists; once prices change, the columns diverge and you can see both what you "spent" then and what it would cost now.

## ⚠️ Reference value vs real dollars (important)

Under a **subscription** login, Claude Code usage is covered by your flat monthly fee — so these dollar figures are **reference value** ("what it would cost at pay-as-you-go API prices"), **not** money billed. The `session_start` event records the detected `billing_mode` (`subscription` / `api_key` / `unknown`), and `cost --billing` surfaces a note — but reports **do not** show it by default.

What the ledger **cannot** know (server-side only): which tokens fell within your subscription allowance vs paid overage, and your true billed dollars. The **Anthropic Console** is authoritative for actual charges. See the [open reconciliation issue](https://github.com/dabeckham/claude-accounting/issues/3).

## A note on magnitude

On long agentic sessions **`cache_read` dominates** — the full context is re-read on every tool round-trip — so a single heavy turn can be several dollars even with little visible output. That's accurate to how the API bills, and it's the accountability signal this project exists to surface.

> **See also:** [THINKING_REEMISSION.md](THINKING_REEMISSION.md) — re-emitting a turn's hidden reasoning into the visible reply converts it from ephemeral to persistent, feeding exactly this `cache_read` line on every later turn.
