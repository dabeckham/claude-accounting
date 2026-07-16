#!/usr/bin/env python
"""Statusline-side limits capture. Claude Code invokes the configured statusLine
command on every statusline refresh, passing session/model/context JSON on stdin
— including (since 2.1.80) `rate_limits`: the SAME 5-hour / weekly plan-usage
meters the desktop app's usage pane shows (used_percentage + resets_at), and
`context_window` utilization. This script:

  1. dumps the full raw payload to ~/.claude/time-tracking/statusline-last.json
     (always; zero-token live view for the web UI / debugging),
  2. appends a `limits` row to the timelog ledger — but only when a meter moved
     (>=0.5pt change in any window's used_percentage) or 15 min passed since the
     last row (heartbeat), so the ledger isn't spammed by every refresh,
  3. prints a one-line status text (harmless if the surface doesn't render it).

Never blocks, never crashes the statusline: everything is wrapped; on any error
it still prints a line and exits 0. Timestamps follow the ledger convention:
epoch (UTC instant) + ts local ISO with offset.
"""
import sys, json, time, os

TT = os.path.join(os.path.expanduser("~"), ".claude", "time-tracking")
LEDGER = os.path.join(TT, "timelog.jsonl")
LAST = os.path.join(TT, "statusline-last.json")
STATE = os.path.join(TT, ".statusline-limits-state.json")
HEARTBEAT_S = 900  # ledger heartbeat row when nothing changed
MOVE_PT = 0.5      # write a row when any window moved this much


def windows(rl):
    """Normalize rate_limits into {name: {'pct': float, 'resets_at': str}}."""
    out = {}
    if isinstance(rl, dict):
        items = rl.items()
    elif isinstance(rl, list):
        items = ((w.get("name") or w.get("window") or str(i), w)
                 for i, w in enumerate(rl))
    else:
        return out
    for name, w in items:
        if not isinstance(w, dict):
            continue
        pct = w.get("used_percentage", w.get("utilization"))
        if pct is None:
            continue
        out[str(name)] = {"pct": round(float(pct), 2),
                          "resets_at": w.get("resets_at")}
    return out


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    now = int(time.time())
    os.makedirs(TT, exist_ok=True)

    # 1. always persist the freshest raw payload (atomic-ish: tmp+rename)
    try:
        tmp = LAST + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"captured_epoch": now,
                       "captured_ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                       "payload": data}, f)
        os.replace(tmp, LAST)
    except Exception:
        pass

    rl = data.get("rate_limits")
    wins = windows(rl)
    ctx = data.get("context_window") or {}
    ctx_pct = ctx.get("used_percentage")

    # 2. throttled ledger append
    try:
        prev = {}
        try:
            with open(STATE, encoding="utf-8") as f:
                prev = json.load(f)
        except Exception:
            prev = {}
        moved = any(abs(w["pct"] - prev.get("wins", {}).get(n, {}).get("pct", -999)) >= MOVE_PT
                    for n, w in wins.items()) or \
                set(wins) != set(prev.get("wins", {}))
        stale = now - prev.get("epoch", 0) >= HEARTBEAT_S
        if wins and (moved or stale):
            sess = (str(data.get("session_id") or ""))[:8]
            cwd = (data.get("workspace") or {}).get("current_dir") or ""
            proj = os.path.basename(cwd.rstrip("/\\")) or "?"
            rec = {"kind": "event", "epoch": now,
                   "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                   "category": "limits", "session": sess, "project": proj,
                   "desc": "statusline sample",
                   "windows": wins}
            if ctx_pct is not None:
                rec["context_pct"] = round(float(ctx_pct), 1)
            with open(LEDGER, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            with open(STATE, "w", encoding="utf-8") as f:
                json.dump({"epoch": now, "wins": wins}, f)
    except Exception:
        pass

    # 3. status text
    try:
        parts = []
        label = {"five_hour": "5h", "seven_day": "wk", "seven_day_opus": "wk-opus",
                 "seven_day_sonnet": "wk-sonnet", "seven_day_oss": "wk-oss"}
        for n, w in wins.items():
            parts.append("%s %d%%" % (label.get(n, n), round(w["pct"])))
        if ctx_pct is not None:
            parts.append("ctx %d%%" % round(float(ctx_pct)))
        print(" | ".join(parts) if parts else "limits: n/a")
    except Exception:
        print("limits: n/a")
    return 0


if __name__ == "__main__":
    sys.exit(main())
