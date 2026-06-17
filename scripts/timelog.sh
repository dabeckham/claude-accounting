#!/bin/sh
# timelog — cross-session, cross-project time-tracking ledger helper.
#
# Appends to ONE global append-only JSONL ledger so every Claude session (any
# project) records work intervals + Don's interactive hours. A future UI/report
# reads the JSONL. Workstation-local; contains NO secrets. Single-line JSON
# appends are atomic (<4 KB), so parallel sessions can write safely.
# Schema + conventions: ~/.claude/time-tracking/README.md
#
# Usage:
#   timelog.sh now
#       -> prints current unix epoch (capture a start: START=$(timelog.sh now))
#   timelog.sh event <category> "<desc>" [session] [project]
#       -> append a point-in-time event at now.
#   timelog.sh interval <category> <start_epoch> <end_epoch|now> "<desc>" [session] [project]
#       -> append a completed work interval (start..end).
#   timelog.sh view [N]      -> last N entries (default 20) as a table + totals
#   timelog.sh today         -> today's entries + per-category totals
#
# Categories (intervals): thinking | coding | deploy | research | review |
#   waiting (on Don) | meeting | other.  Events (mostly hook-written):
#   session_start | prompt | turn_end.
LEDGER="$HOME/.claude/time-tracking/timelog.jsonl"
mkdir -p "$HOME/.claude/time-tracking" 2>/dev/null

cmd="$1"; [ $# -gt 0 ] && shift

case "$cmd" in
  now)
    date +%s
    ;;

  event)
    CAT="$1"; DESC="$2"; SESS="${3:-cli}"; PROJ="${4:-$(basename "$PWD")}"
    python - "$CAT" "$DESC" "$SESS" "$PROJ" "$LEDGER" <<'PY'
import sys, json, time
cat, desc, sess, proj, ledger = sys.argv[1:6]
now = int(time.time())
rec = {"kind":"event","epoch":now,"ts":time.strftime("%Y-%m-%dT%H:%M:%S%z"),
       "category":cat,"session":sess,"project":proj,"desc":desc[:200]}
with open(ledger,"a",encoding="utf-8") as f:
    f.write(json.dumps(rec)+"\n")
print("logged event:", cat, "-", desc[:60])
PY
    ;;

  interval)
    CAT="$1"; START="$2"; END="$3"; DESC="$4"; SESS="${5:-cli}"; PROJ="${6:-$(basename "$PWD")}"
    [ "$END" = "now" ] && END=$(date +%s)
    python - "$CAT" "$START" "$END" "$DESC" "$SESS" "$PROJ" "$LEDGER" <<'PY'
import sys, json, time
cat, start, end, desc, sess, proj, ledger = sys.argv[1:8]
start, end = int(start), int(end)
iso = lambda e: time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(e))
rec = {"kind":"interval","start_epoch":start,"start_ts":iso(start),
       "end_epoch":end,"end_ts":iso(end),"dur_s":end-start,
       "epoch":end,"ts":iso(end),
       "category":cat,"session":sess,"project":proj,"desc":desc[:200]}
with open(ledger,"a",encoding="utf-8") as f:
    f.write(json.dumps(rec)+"\n")
d = end-start
print(f"logged interval: {cat} {d//60}m{d%60}s - {desc[:60]}")
PY
    ;;

  view|today)
    python - "$cmd" "${1:-20}" "$LEDGER" <<'PY'
import sys, json, time, os
mode, arg, ledger = sys.argv[1], sys.argv[2], sys.argv[3]
if not os.path.exists(ledger):
    print("(empty ledger)"); sys.exit()
rows = [json.loads(l) for l in open(ledger,encoding="utf-8") if l.strip()]
if mode == "today":
    today = time.strftime("%Y-%m-%d")
    rows = [r for r in rows if r.get("ts","").startswith(today)]
else:
    try: n = int(arg)
    except ValueError: n = 20
    rows = rows[-n:]
print(f"{'time':19} {'kind':8} {'category':12} {'dur':>7} {'project':16} desc")
print("-"*100)
tot = {}
for r in rows:
    dur = r.get("dur_s")
    durs = f"{dur//60}m{dur%60}s" if dur is not None else ""
    if dur is not None:
        tot[r.get('category','?')] = tot.get(r.get('category','?'),0) + dur
    print(f"{r.get('ts','')[:19]:19} {r.get('kind',''):8} {r.get('category',''):12} {durs:>7} {r.get('project','')[:16]:16} {r.get('desc','')[:48]}")
if tot:
    print("\n-- interval totals --")
    for k,v in sorted(tot.items(), key=lambda x:-x[1]):
        print(f"  {k:12} {v//3600}h{(v%3600)//60:02d}m")
PY
    ;;

  cost)
    # Price the turn_end token rows from pricing.json (report-time costing).
    # arg: "today" (default) | "all" | N (last N turn_end rows).
    python - "${1:-today}" "$LEDGER" "$HOME/.claude/time-tracking/pricing.json" <<'PY'
import sys, json, os, time
mode, ledger, pricing_path = sys.argv[1], sys.argv[2], sys.argv[3]
if not os.path.exists(ledger):
    print("(empty ledger)"); sys.exit()
P = json.load(open(pricing_path, encoding="utf-8"))
models, default = P.get("models", {}), P.get("default", {})

def rate(model):
    return models.get(model, default)

def cost_of(r):
    pr = rate(r.get("model", ""))
    return (
        (r.get("in_tokens", 0)       * pr.get("input", 0))
      + (r.get("out_tokens", 0)      * pr.get("output", 0))
      + (r.get("cache_read", 0)      * pr.get("cache_read", 0))
      + (r.get("cache_write_5m", 0)  * pr.get("cache_write_5m", 0))
      + (r.get("cache_write_1h", 0)  * pr.get("cache_write_1h", 0))
    ) / 1_000_000.0

rows = [json.loads(l) for l in open(ledger, encoding="utf-8") if l.strip()]
turns = [r for r in rows if r.get("category") == "turn_end" and "in_tokens" in r]
if mode == "today":
    today = time.strftime("%Y-%m-%d")
    turns = [r for r in turns if r.get("ts", "").startswith(today)]
elif mode != "all":
    try: turns = turns[-int(mode):]
    except ValueError: pass

if not turns:
    print("(no priced turn_end rows yet — the Stop hook fills these on the next session)")
    sys.exit()

print(f"{'time':17} {'model':18} {'in':>7} {'out':>7} {'cache_rd':>9} {'$cost':>8}  project")
print("-"*82)
tot, by_model, by_proj = 0.0, {}, {}
for r in turns:
    c = cost_of(r); tot += c
    by_model[r.get("model","?")] = by_model.get(r.get("model","?"),0)+c
    by_proj[r.get("project","?")] = by_proj.get(r.get("project","?"),0)+c
    print(f"{r.get('ts','')[:16]:17} {(r.get('model','') or '')[:18]:18} "
          f"{r.get('in_tokens',0):>7} {r.get('out_tokens',0):>7} {r.get('cache_read',0):>9} "
          f"{c:>8.4f}  {r.get('project','')[:20]}")
print("-"*82)
print(f"TOTAL  {len(turns)} turns   ${tot:.4f}")
print("by model: " + ", ".join(f"{k} ${v:.4f}" for k,v in sorted(by_model.items(), key=lambda x:-x[1])))
print("by project: " + ", ".join(f"{k} ${v:.4f}" for k,v in sorted(by_proj.items(), key=lambda x:-x[1])))
PY
    ;;

  *)
    echo "usage: timelog.sh {now | event <cat> <desc> [sess] [proj] | interval <cat> <start> <end|now> <desc> [sess] [proj] | view [N] | today | cost [today|all|N]}"
    ;;
esac
