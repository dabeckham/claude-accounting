#!/usr/bin/env python
"""Hook-side time logger. Reads the Claude Code hook event JSON on stdin and
appends ONE event line to the ledger, then exits 0. Invoked by timelog-hook.sh
from the global SessionStart / UserPromptSubmit / Stop hooks.

argv[1] = event category: session_start | prompt | turn_end

For turn_end, also parses the tail of the transcript (path from the hook event)
to record the just-finished turn's model + token usage for accountability:
  model, in_tokens, out_tokens, cache_read, cache_write_5m, cache_write_1h,
  web_search, web_fetch, used_thinking, msgs — and stamps cost_usd + pricing_from
  using the pricing schedule in effect that day (the immutable 'Actual' spend).
Token usage and model are NOT hook fields; they live in the transcript, which is
the only place per-turn usage is persisted. session_start records billing_mode
(subscription | api_key | unknown) from the auth method. The effort/reasoning level
is not recorded anywhere and can't be auto-detected; it is captured via the in-band
"effort: <level>" tag on the prompt event (with carry-forward).

Writes nothing to stdout so it never injects context or blocks a turn.
"""
import sys, json, time, os, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import timelog_core as core

cat = sys.argv[1] if len(sys.argv) > 1 else "event"
ledger = os.path.join(os.path.expanduser("~"), ".claude", "time-tracking", "timelog.jsonl")
os.makedirs(os.path.dirname(ledger), exist_ok=True)

try:
    data = json.load(sys.stdin)
except Exception:
    data = {}

sess = (str(data.get("session_id") or ""))[:8]
cwd = data.get("cwd") or os.getcwd()
proj = os.path.basename(cwd.rstrip("/\\")) or "?"
desc = ""

rec = {"kind": "event", "epoch": int(time.time()),
       "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
       "category": cat, "session": sess, "project": proj, "desc": desc}


if cat == "prompt":
    text = str(data.get("prompt") or "")
    rec["desc"] = text.replace("\n", " ").strip()[:160]
    # In-band effort tag: Don writes "effort: high" (or =, levels per the Opus 4.8
    # desktop UI). Accurate because it's his own words — the value can't be read
    # from the API call or disk. "ultra" is accepted as an alias for ultracode.
    # If no tag this turn, carry forward the last tagged level FOR THIS SESSION
    # (Don moves between sessions constantly and their effort differs), marked
    # effort_certain=false so reporting can tell tagged from assumed. A session
    # never tagged has no carry-forward and stays unlabeled. State is keyed by
    # session id in timelog_core (~/.claude/.timelog-last-effort.json).
    m = re.search(r"effort\s*[:=]\s*(low|medium|high|extra|max|ultracode|ultra)\b", text, re.I)
    if m:
        lvl = m.group(1).lower()
        lvl = "ultracode" if lvl == "ultra" else lvl
        rec["effort"] = lvl
        rec["effort_certain"] = True
        core.set_session_effort(sess, lvl)
    else:
        last = core.read_session_effort(sess)
        if last:
            rec["effort"] = last
            rec["effort_certain"] = False
elif cat == "session_start":
    rec["desc"] = str(data.get("source") or "")
    # Billing channel (stored, not shown on reports unless asked). Detected from the
    # auth method: an API key env var → pay-as-you-go; otherwise an OAuth/login
    # credential → subscription. This is the channel only — it does NOT claim which
    # tokens fell within a subscription allowance vs paid overage (Console-only).
    if os.environ.get("ANTHROPIC_API_KEY"):
        rec["billing_mode"] = "api_key"
    elif os.path.exists(os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")):
        rec["billing_mode"] = "subscription"
    else:
        rec["billing_mode"] = "unknown"
elif cat == "turn_end":
    # Parse the just-finished turn from the transcript tail (bounded for speed —
    # transcripts can be tens of MB). Sum usage over assistant messages since the
    # last real user prompt (tool-result messages also have type "user" but carry
    # a toolUseResult key, so they don't count as the turn boundary).
    tp = data.get("transcript_path")
    # Normalize path: Claude Code may pass a native Windows path (C:\...) or an
    # MSYS-style path (/c/Users/...). Native Windows python can't stat the /c/
    # form, so convert it when the literal path doesn't exist.
    if tp and not os.path.exists(tp):
        import re
        m = re.match(r"^/([a-zA-Z])/(.*)$", tp)
        if m:
            win = m.group(1).upper() + ":/" + m.group(2)
            if os.path.exists(win):
                tp = win
    try:
        if tp and os.path.exists(tp):
            with open(tp, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                window = 2_000_000
                f.seek(max(0, size - window))
                blob = f.read()
            text = blob.decode("utf-8", "ignore").split("\n")
            if size > window:
                text = text[1:]  # drop the partial first line
            rows = []
            for l in text:
                l = l.strip()
                if not l:
                    continue
                try:
                    rows.append(json.loads(l))
                except Exception:
                    pass
            # Sum the just-finished turn (last prompt boundary -> end) via the
            # shared summarizer, so the live hook and the historical backfill count
            # a turn the exact same way.
            start = core.last_turn_start(rows)
            rec.update(core.summarize_turn(rows[start:]))
            # Lock in the cost at the prices in effect today (immutable Actual spend).
            c, pfrom = core.price_turn(rec)
            if c is not None:
                rec["cost_usd"] = c
                rec["pricing_from"] = pfrom
    except Exception:
        pass

try:
    with open(ledger, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
except Exception:
    pass
