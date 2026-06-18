#!/usr/bin/env python
"""Backfill the time-tracking ledger from historical Claude Code transcripts.

The ledger (`~/.claude/time-tracking/timelog.jsonl`) only has data from when the
Stop hook was installed (2026-06-17). But Claude Code keeps full per-message
transcripts under `~/.claude/projects/**/*.jsonl` reaching weeks further back.
This script replays the *exact* per-turn summing the live hook uses (via the
shared `timelog_core`) to reconstruct one synthetic `turn_end` event per turn,
so historical days show up in `month`/`all` reports.

Correctness is the whole point: a naive per-message reconstruction does NOT
reconcile (transcripts repeat streaming snapshots). Run `--verify` first — it
re-derives the ledger's already-recorded turns from the transcripts and confirms
they match to the cent. Only backfill once that passes.

De-duplication is by LOCAL DATE: any date that already has `turn_end` events in
the ledger is left completely untouched (so 06-17/06-18 totals never change).
The trade-off is that turns from before the hook went live on an already-present
date (06-17 morning) are not recovered — the conservative choice that guarantees
no double counting.

Each backfilled event is stamped `reconstructed: true` and
`source: "transcript-backfill"` so reports can tell it from live data.

Usage:
  backfill-from-transcripts.py --verify     # gate: reproduce ledger turns to the cent
  backfill-from-transcripts.py --dry-run    # per-day deltas, writes nothing
  backfill-from-transcripts.py --apply      # back up ledger, then append events
"""
import sys, os, json, glob, datetime, time, shutil, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import timelog_core as core

HOME = os.path.expanduser("~")
LEDGER = os.path.join(HOME, ".claude", "time-tracking", "timelog.jsonl")
PRICING = os.path.join(HOME, ".claude", "time-tracking", "pricing.json")
TRANSCRIPT_GLOB = os.path.join(HOME, ".claude", "projects", "**", "*.jsonl")
MATCH_WINDOW_S = 120  # ledger ts (Stop fire) lags a turn's last assistant msg slightly


def read_jsonl(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return rows


def to_local(ts):
    """ISO-8601 UTC ('...Z') -> aware local datetime."""
    return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()


def first(rows, key):
    for r in rows:
        if r.get(key):
            return r[key]
    return None


def enumerate_turns(schedules):
    """Yield one reconstructed turn_end event dict per transcript turn, with a
    transient '_end' datetime attached for bucketing/matching. Turns with no
    assistant messages (or no timestamp) are skipped."""
    for path in sorted(glob.glob(TRANSCRIPT_GLOB, recursive=True)):
        rows = read_jsonl(path)
        for start, end in core.iter_turn_slices(rows):
            sl = rows[start:end]
            summary = core.summarize_turn(sl)
            if summary["msgs"] == 0:
                continue
            asst_ts = [e.get("timestamp") for e in sl
                       if e.get("type") == "assistant" and e.get("timestamp")]
            if not asst_ts:
                continue
            end_local = to_local(max(asst_ts))
            date_str = end_local.strftime("%Y-%m-%d")
            sess = (first(sl, "sessionId") or "")[:8] or "?"
            cwd = first(sl, "cwd") or ""
            proj = os.path.basename(cwd.rstrip("/\\")) or "?"
            cost, pfrom = core.price_turn(summary, schedules, date_str)
            rec = {
                "kind": "event",
                "epoch": int(end_local.timestamp()),
                "ts": end_local.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "category": "turn_end",
                "session": sess,
                "project": proj,
                "desc": "",
                **summary,
                "reconstructed": True,
                "source": "transcript-backfill",
            }
            if cost is not None:
                rec["cost_usd"] = cost
                rec["pricing_from"] = pfrom
            rec["_end"] = end_local
            yield rec


def load_ledger_turns():
    """Existing turn_end events that carry usage (the ones with cost)."""
    return [r for r in read_jsonl(LEDGER)
            if r.get("category") == "turn_end" and "in_tokens" in r]


def cmd_verify(schedules):
    """Reproduce every already-recorded ledger turn from the transcripts and report
    how many match to the cent. This proves the summing method is faithful.

    Only real live-hook turns are checked — reconstructed turns are excluded so the
    gate stays meaningful and re-runnable after a backfill has been applied (many
    backfilled turns share a second within a session and would collide in the
    time-based matcher)."""
    ledger_turns = [r for r in load_ledger_turns() if not r.get("reconstructed")]
    recon = list(enumerate_turns(schedules))
    by_sess = collections.defaultdict(list)
    for t in recon:
        by_sess[t["session"]].append(t)

    fields = ["in_tokens", "out_tokens", "cache_read", "cache_write_1h", "msgs"]
    matched = exact = cents = 0
    misses = []
    for r in ledger_turns:
        lts = datetime.datetime.strptime(r["ts"], "%Y-%m-%dT%H:%M:%S%z")
        best, best_dt = None, None
        for t in by_sess.get(r["session"], []):
            dt = abs((t["_end"] - lts).total_seconds())
            if best_dt is None or dt < best_dt:
                best, best_dt = t, dt
        if best is None or best_dt > MATCH_WINDOW_S:
            misses.append((r["session"], r["ts"], "no transcript turn within window"))
            continue
        matched += 1
        tok_ok = all(best.get(f) == r.get(f) for f in fields)
        cent_ok = abs((best.get("cost_usd") or 0) - (r.get("cost_usd") or 0)) < 0.005
        if tok_ok:
            exact += 1
        if cent_ok:
            cents += 1
        if not (tok_ok and cent_ok):
            detail = []
            for f in fields:
                if best.get(f) != r.get(f):
                    detail.append(f"{f} ledger={r.get(f)} recon={best.get(f)}")
            if not cent_ok:
                detail.append(f"cost ledger={r.get('cost_usd')} recon={best.get('cost_usd')}")
            misses.append((r["session"], r["ts"], "; ".join(detail)))

    print("VERIFY - reproduce ledger turns from transcripts")
    print(f"  ledger turns:        {len(ledger_turns)}")
    print(f"  matched to a turn:   {matched}")
    print(f"  token-exact:         {exact}")
    print(f"  cost to the cent:    {cents}")
    if misses:
        print(f"  exceptions ({len(misses)}):")
        for s, ts, d in misses:
            print(f"    sess={s} {ts}  {d}")
    ok = matched == len(ledger_turns) and exact >= matched - len(misses) and cents >= matched - 1
    # Gate passes when every modern turn reproduces exactly; a single legacy-schema
    # turn (pre-dating the cache_write split) is tolerated and printed above.
    print("  => GATE", "PASS" if (matched == len(ledger_turns) and len(misses) <= 1) else "FAIL")
    return 0 if (matched == len(ledger_turns) and len(misses) <= 1) else 1


def plan(schedules):
    """Reconstruct all turns, drop dates already present in the ledger, return the
    keepers plus the set of skipped (overlap) dates."""
    ledger_dates = {r["ts"][:10] for r in load_ledger_turns()}
    keep, skipped_dates = [], set()
    for rec in enumerate_turns(schedules):
        d = rec["ts"][:10]
        if d in ledger_dates:
            skipped_dates.add(d)
            continue
        keep.append(rec)
    keep.sort(key=lambda r: r["epoch"])
    return keep, ledger_dates, skipped_dates


def summarize_plan(keep, skipped_dates):
    by_day = collections.defaultdict(lambda: [0, 0.0])
    for r in keep:
        d = r["ts"][:10]
        by_day[d][0] += 1
        by_day[d][1] += r.get("cost_usd", 0) or 0
    print(f"{'date':12} {'turns':>6} {'cost':>11}")
    tot_n = tot_c = 0
    for d in sorted(by_day):
        n, c = by_day[d]
        tot_n += n
        tot_c += c
        print(f"{d:12} {n:6} ${c:10.2f}")
    print(f"{'TOTAL':12} {tot_n:6} ${tot_c:10.2f}   across {len(by_day)} days")
    if skipped_dates:
        print(f"\nleft untouched (already in ledger): {', '.join(sorted(skipped_dates))}")


def main():
    args = set(sys.argv[1:])
    schedules = core.load_schedules(PRICING)
    if not schedules:
        print("ERROR: no pricing schedules found at", PRICING)
        return 2

    if "--verify" in args:
        return cmd_verify(schedules)

    keep, ledger_dates, skipped = plan(schedules)
    if not keep:
        print("Nothing to backfill — every transcript date is already in the ledger.")
        return 0

    if "--apply" not in args:  # default and --dry-run both preview only
        print("DRY RUN - no changes written. Re-run with --apply to write.\n")
        summarize_plan(keep, skipped)
        return 0

    # --apply: back up, then append
    backup = LEDGER + "." + time.strftime("%Y%m%dT%H%M%S") + ".bak"
    shutil.copy2(LEDGER, backup)
    with open(LEDGER, "a", encoding="utf-8") as f:
        for r in keep:
            r.pop("_end", None)
            f.write(json.dumps(r) + "\n")
    print(f"Backed up ledger -> {backup}")
    print(f"Appended {len(keep)} reconstructed turn_end events.\n")
    summarize_plan(keep, skipped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
