# Claude Usage: Time Tracking and Cost Analysis

A lightweight, file-based accounting layer for **Claude Code** that records — automatically, with zero effort per turn — how long you spend in interactive sessions and what each turn costs. It captures per‑turn **timing, model, token usage, and dollar cost** into a single append‑only ledger, plus optional **task‑level intervals** and an **in‑band reasoning‑effort tag**. A future UI/report can read the ledger directly.

> Built and dogfooded on Windows (Claude Code desktop) but the design is OS‑agnostic — it relies only on Claude Code's hooks, the session transcript, and a small shell+Python helper.

---

## Why

If you use Claude Code seriously, two questions come up fast:

1. **How much time am I actually spending** in these sessions, and how long does each task take?
2. **What is it costing** — per turn, per project, per day?

Claude Code doesn't surface either directly. This project answers both by tapping the two signals that *are* available locally: **lifecycle hooks** (turn boundaries) and the **session transcript** (model + token usage). It never guesses or fabricates — anything it can't measure reliably is simply left unrecorded.

---

## What it captures

| Signal | Source | Reliability |
|---|---|---|
| Session start / resume / compact | `SessionStart` hook | ✅ automatic |
| You become active / a turn begins | `UserPromptSubmit` hook | ✅ automatic |
| A turn ends (your "waiting" gap begins) | `Stop` hook | ✅ automatic |
| Model used per turn | session transcript | ✅ automatic |
| Token usage per turn (input / output / cache read / cache write 5m & 1h) | session transcript | ✅ automatic |
| Web search / fetch counts, extended‑thinking flag | session transcript | ✅ automatic |
| Dollar cost per turn (locked in at that day's prices + present-day re-price) | tokens × dated pricing schedule | ✅ stamped at write time |
| Billing channel (subscription vs api_key) | auth method, per session | ✅ stored (shown only on request) |
| Task‑level intervals (`thinking` / `coding` / `deploy` / …) | the agent logs them | ✅ best‑effort |
| Reasoning **effort** level | **in‑band tag** in your message | ⚠️ manual tag (see below) |

From the automatic events a report derives:

- **agent turn time** = `turn_end − prompt`
- **your turnaround / idle** = next `prompt − turn_end`
- **session span** from `session_start`

---

## How it works

```
        ┌──────────────────────── Claude Code ────────────────────────┐
        │                                                              │
  you ──┤  UserPromptSubmit hook ─┐                                    │
        │                         │                                    │
        │  (agent works…)         ├─► timelog-hook.sh ─► timelog-hook.py│
        │                         │        (reads hook JSON on stdin,   │
        │  Stop hook ─────────────┘         and for turn_end also reads │
        │                                   the transcript tail)        │
        │  SessionStart hook ─────────────► …                          │
        └──────────────────────────────────────────────┬──────────────┘
                                                         │ append one JSON line
                                                         ▼
                              ~/.claude/time-tracking/timelog.jsonl   (the ledger)
                                                         │
                          timelog.sh view|today|cost  ◄──┘   (+ future UI)
```

Two layers:

1. **Automatic (hooks).** `SessionStart`, `UserPromptSubmit`, and `Stop` hooks fire a tiny logger that appends one event per occurrence. The `Stop` hook additionally parses the **tail of the session transcript** to pull the just‑finished turn's model and token usage — these are *not* in the hook payload, they live only in the transcript.
2. **Semantic (agent‑logged).** The agent brackets meaningful work with `timelog.sh interval <category> <start> now "<desc>"` so a turn can be broken into `thinking` vs `coding` vs `deploy`, which the hooks can't see.

Everything lands in **one append‑only JSONL ledger**. Single‑line appends are atomic, so parallel sessions can't corrupt it. Each turn's **cost is locked in** at the prices in effect that day (stamped on the row from a *dated* pricing schedule), so a later price change never rewrites history — and reports also show a present‑day "Today" column. See [`docs/COST.md`](docs/COST.md).

---

## Install

> Requires Claude Code and a POSIX shell + Python 3 (both already present on a typical Claude Code machine; on Windows the bundled Git‑Bash `sh` and a `python` on PATH are sufficient).

1. **Copy the scripts and config** into your Claude config dir:

   ```sh
   cp scripts/timelog.sh scripts/timelog-hook.sh scripts/timelog-hook.py scripts/timelog_core.py \
      scripts/timelog-statusline.sh scripts/timelog-statusline.py ~/.claude/
   mkdir -p ~/.claude/time-tracking
   cp config/pricing.json ~/.claude/time-tracking/
   ```

2. **Wire the hooks** into `~/.claude/settings.json` (user‑level = all projects). Merge the `hooks` block from [`config/settings.example.json`](config/settings.example.json) into your existing settings — and optionally the `statusLine` block, which pins this session's current effort + model beneath the input box. Hooks take effect on the **next** session start.

3. **(Optional) Add the cross‑session instruction** so every session feeds the ledger and honors the effort tag — see [`docs/AGENT_INSTRUCTIONS.md`](docs/AGENT_INSTRUCTIONS.md) for the snippet to drop into your global `~/.claude/CLAUDE.md`.

4. **Verify** after your next turn:

   ```sh
   sh ~/.claude/timelog.sh today
   sh ~/.claude/timelog.sh cost today
   ```

---

## Usage

```sh
# point-in-time / interval logging (the agent does this; you can too)
sh ~/.claude/timelog.sh now                         # print current epoch
sh ~/.claude/timelog.sh interval coding "$START" now "implement merge pass"

# views
sh ~/.claude/timelog.sh today                       # today's entries + per-category totals
sh ~/.claude/timelog.sh view 30                     # last 30 entries
sh ~/.claude/timelog.sh cost today                  # today's turns: Actual + Today $ columns
sh ~/.claude/timelog.sh cost all                    # all priced turns
sh ~/.claude/timelog.sh cost all --billing          # also append the billing-channel note
```

### Reasoning‑effort tagging

The effort/reasoning level you pick in the Claude desktop UI is **not recoverable** from the transcript or disk (see [`docs/EFFORT.md`](docs/EFFORT.md) for the full investigation). The reliable capture is **in‑band**: write `effort: <level>` (or `effort=<level>`) anywhere in a message.

- Levels (Opus 4.8 desktop UI): `low · medium · high · extra · max · ultracode` (`ultra` aliases `ultracode`).
- A tag sets `effort` + `effort_certain: true` and is **remembered per session**; untagged messages **inherit that session's** last tagged level with `effort_certain: false` (assumed), so you don't retype it every turn. Carry‑forward is session‑scoped, so a tag in one session never bleeds into a different one.
- No tag and no prior → no `effort` field (never guessed). Reports can treat "uncertain" as accurate while still distinguishing it from explicitly tagged turns.
- A **status line** (optional) shows this session's current effort + model beneath the input box, e.g. `● Last effort: medium · Opus 4.8` — a live reminder of what untagged turns will inherit.

---

## Repository layout

```
claude-accounting/
├── README.md                     ← you are here
├── LICENSE                       ← MIT
├── scripts/
│   ├── timelog.sh                ← agent/CLI helper: now | event | interval | view | today | cost
│   ├── timelog-hook.sh           ← hook entry point (forwards stdin to the .py)
│   ├── timelog-hook.py           ← appends events; parses transcript tail for tokens/model; parses effort tag
│   ├── timelog-statusline.sh     ← statusLine entry point (forwards stdin to the .py)
│   ├── timelog-statusline.py     ← renders this session's last effort + model for the status bar
│   ├── timelog_core.py           ← shared turn summing + pricing + per-session effort state (imported by the hook, statusline AND the backfill)
│   ├── backfill-from-transcripts.py ← reconstruct historical turn_end events from old transcripts
│   └── timelog-report.py         ← deterministic report generator (engine behind /accounting)
├── config/
│   ├── pricing.json              ← dated pricing schedules (append a new one when rates change)
│   └── settings.example.json     ← the hooks block to merge into ~/.claude/settings.json
├── commands/
│   └── accounting.md             ← the /accounting slash command (copy into ~/.claude/commands/)
└── docs/
    ├── SCHEMA.md                 ← the JSONL ledger schema + conventions
    ├── HOOKS.md                  ← how the three hooks work + the transcript-parsing approach
    ├── COST.md                   ← cost derivation + pricing/cache-rate details
    ├── BACKFILL.md               ← reconstructing history from old transcripts (method + the verify gate)
    ├── EFFORT.md                 ← why effort can't be auto-detected; in-band tagging; the relay option
    └── AGENT_INSTRUCTIONS.md     ← the cross-session CLAUDE.md snippet
```

## Reporting — the `/accounting` command

For a readable report instead of raw JSONL, install the slash command + the report engine:

```sh
cp scripts/timelog-report.py ~/.claude/timelog-report.py
mkdir -p ~/.claude/commands && cp commands/accounting.md ~/.claude/commands/
# then restart Claude Code so /accounting registers (slash commands load at startup)
```

Invoke **`/accounting [today|week|month|all|N] [--billing]`** in Claude Code, or run the engine directly any time:

```sh
python ~/.claude/timelog-report.py week            # default
python ~/.claude/timelog-report.py all --billing
```

It prints sessions & interactive time, a time breakdown (agent working time vs your idle/reading vs logged task intervals), cost (Actual + Today), token totals, and the effort mix — all computed deterministically from the ledger.

> Slash commands register **at Claude Code startup**, so a freshly-installed `/accounting` only appears in a new session. Until then, run `timelog-report.py` directly.

---

## Further reading — the economics behind the numbers

Two self‑contained narrative write‑ups, dogfooded from this very ledger, explain *why* the numbers look the way they do:

- **[Why a Tiny Reply "Costs" 54,000 Tokens](https://htmlpreview.github.io/?https://github.com/dabeckham/claude-accounting/blob/main/docs/token-accounting-conversation.html)** — how per‑turn token accounting actually works: every turn re‑sends the full context, prompt caching makes the reads cheap (a tenth of input price), what it costs to serve, and how fast subscription usage piles up. *(source: [`docs/token-accounting-conversation.html`](docs/token-accounting-conversation.html))*
- **[Now Let's Talk About Limits](https://htmlpreview.github.io/?https://github.com/dabeckham/claude-accounting/blob/main/docs/now-lets-talk-about-limits.html)** — the 5‑hour and weekly rate limits reverse‑engineered from the ledger: what they actually count (fresh input + output, *not* cache), the per‑plan ceilings, and what a maxed‑out week costs to serve. *(source: [`docs/now-lets-talk-about-limits.html`](docs/now-lets-talk-about-limits.html))*

> These are standalone HTML (inline styles, no dependencies); the links above render them via htmlpreview, or open the files in `docs/` locally.

---

## Backfilling history from old transcripts

The hooks only start logging once installed, so days before that are blank. But Claude Code keeps full per‑message transcripts under `~/.claude/projects/**/*.jsonl` going back weeks, and every assistant message carries the model + token usage needed to rebuild a turn. **`backfill-from-transcripts.py`** replays those transcripts and appends one reconstructed `turn_end` per turn.

The catch is that a *naive* per‑message sum doesn't reconcile — transcripts repeat streaming snapshots, so counting them over/under‑counts. The backfill therefore reuses the **exact same per‑turn summer the live hook uses** (`timelog_core.py`), so a reconstructed turn is counted byte‑for‑byte the way it would have been counted live.

```sh
python ~/.claude/backfill-from-transcripts.py --verify     # gate: reproduce known days to the cent
python ~/.claude/backfill-from-transcripts.py --dry-run    # per-day deltas, writes nothing
python ~/.claude/backfill-from-transcripts.py --apply      # back up the ledger, then append
```

- **`--verify` is the gate.** It re‑derives the turns the live hook already recorded and confirms they match **to the cent** before you trust the method. (One legacy row — the very first turn ever logged, written by a pre‑`cache_write` hook revision — is reported as a known exception.)
- **No double counting.** De‑dup is by **local date**: any date that already has `turn_end` events is left completely untouched, so existing day totals never change. Re‑running `--apply` is idempotent. (Trade‑off: turns from *before* the hook went live on an already‑present date aren't recovered — the safe choice.)
- **Provenance.** Every reconstructed row is stamped `reconstructed: true` and `source: "transcript-backfill"`, and priced with the schedule in effect **on the turn's own date**.
- **Safety.** `--apply` writes a timestamped `timelog.jsonl.<ts>.bak` before appending.

---

## Limitations (read before trusting the numbers)

- **Claude Code only.** Hooks fire only inside Claude Code on the machine where they're installed. They do **not** see claude.ai web, the desktop/mobile chat apps, or raw API usage. For all‑surface, account‑wide totals, the authoritative source is the [Anthropic Console](https://console.anthropic.com) usage/billing.
- **Per machine.** `~/.claude` is not synced across machines; install on each.
- **Effort is manual.** The level isn't persisted anywhere readable, so it's captured only via the in‑band tag (with carry‑forward). See [`docs/EFFORT.md`](docs/EFFORT.md).
- **Cost is an estimate.** Token counts are exact (from the transcript); the dollar figure depends on the pricing table being current — verify rates at <https://platform.claude.com/docs/en/pricing>.

---

## Contributing / project conventions

Changes are tracked as **GitHub Issues** (one per feature or bug), closed with a detailed explanation of what changed and why. Documentation is updated in the same change. See the open issues for planned work (e.g. the optional request‑intercepting relay that would capture effort automatically).

## License

[MIT](LICENSE).
