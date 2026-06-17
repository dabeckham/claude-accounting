#!/usr/bin/env python
"""Hook-side time logger. Reads the Claude Code hook event JSON on stdin and
appends ONE event line to the ledger, then exits 0. Invoked by timelog-hook.sh
from the global SessionStart / UserPromptSubmit / Stop hooks.

argv[1] = event category: session_start | prompt | turn_end

For turn_end, also parses the tail of the transcript (path from the hook event)
to record the just-finished turn's model + token usage for accountability:
  model, in_tokens, out_tokens, cache_read, cache_creation, web_search, web_fetch,
  used_thinking, msgs.
Token usage and model are NOT hook fields; they live in the transcript, which is
the only place per-turn usage is persisted. The effort/reasoning level a user
selects is not recorded anywhere, so it cannot be logged (model id is the proxy).

Writes nothing to stdout so it never injects context or blocks a turn.
"""
import sys, json, time, os, re

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
    # If no tag this turn, carry forward the last tagged level but mark it
    # effort_certain=false, so reporting can tell tagged from assumed (Don: treat
    # uncertain as accurate but distinguishable). No prior tag → no effort field.
    state = os.path.join(os.path.expanduser("~"), ".claude", ".timelog-last-effort")
    m = re.search(r"effort\s*[:=]\s*(low|medium|high|extra|max|ultracode|ultra)\b", text, re.I)
    if m:
        lvl = m.group(1).lower()
        lvl = "ultracode" if lvl == "ultra" else lvl
        rec["effort"] = lvl
        rec["effort_certain"] = True
        try:
            with open(state, "w", encoding="utf-8") as f:
                f.write(lvl)
        except Exception:
            pass
    else:
        try:
            last = open(state, encoding="utf-8").read().strip()
        except Exception:
            last = ""
        if last:
            rec["effort"] = last
            rec["effort_certain"] = False
elif cat == "session_start":
    rec["desc"] = str(data.get("source") or "")
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
            start = 0
            for i in range(len(rows) - 1, -1, -1):
                e = rows[i]
                if e.get("type") == "user" and "toolUseResult" not in e:
                    start = i
                    break
            tin = tout = tcr = cw5 = cw1 = cc_total = ws = wf = nmsg = 0
            models, thinking = set(), False

            def _accum(d):
                # Add one usage-like dict's token counts to the running totals.
                global tin, tout, tcr, cw5, cw1, cc_total
                tin += d.get("input_tokens", 0) or 0
                tout += d.get("output_tokens", 0) or 0
                tcr += d.get("cache_read_input_tokens", 0) or 0
                cc_total += d.get("cache_creation_input_tokens", 0) or 0
                cc = d.get("cache_creation") or {}
                cw5 += cc.get("ephemeral_5m_input_tokens", 0) or 0
                cw1 += cc.get("ephemeral_1h_input_tokens", 0) or 0

            for e in rows[start:]:
                if e.get("type") != "assistant":
                    continue
                m = e.get("message", {}) or {}
                if m.get("model"):
                    models.add(m["model"])
                u = m.get("usage", {}) or {}
                iters = u.get("iterations")
                if iters:
                    for it in iters:
                        _accum(it)
                else:
                    _accum(u)
                stu = u.get("server_tool_use", {}) or {}
                ws += stu.get("web_search_requests", 0) or 0
                wf += stu.get("web_fetch_requests", 0) or 0
                for c in (m.get("content") or []):
                    if isinstance(c, dict) and c.get("type") == "thinking":
                        thinking = True
                nmsg += 1
            # If the split buckets are empty but a total was reported, attribute it
            # to the 5-minute bucket (the default cache TTL) so cost isn't undercounted.
            if cw5 == 0 and cw1 == 0 and cc_total > 0:
                cw5 = cc_total
            models.discard("<synthetic>")
            rec["model"] = sorted(models)[0] if len(models) == 1 else ",".join(sorted(models))
            rec["in_tokens"] = tin
            rec["out_tokens"] = tout
            rec["cache_read"] = tcr
            rec["cache_write_5m"] = cw5
            rec["cache_write_1h"] = cw1
            rec["web_search"] = ws
            rec["web_fetch"] = wf
            rec["used_thinking"] = thinking
            rec["msgs"] = nmsg
    except Exception:
        pass

try:
    with open(ledger, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
except Exception:
    pass
