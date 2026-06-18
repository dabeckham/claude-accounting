#!/usr/bin/env python
"""Accounting report over the Claude Code time-tracking ledger.

Reads ~/.claude/time-tracking/timelog.jsonl (+ pricing.json) and prints a
readable report: sessions & interactive time, time breakdown, cost (Actual vs
Today), tokens, and effort. Numbers are computed deterministically here — never
estimated by the model.

Usage:
  report.py [today|week|month|all|N] [--billing]
    period: today (default week) | week (7d) | month (30d) | all | N (last N days)
    --billing: append the billing-channel / reference-value note
"""
import sys, os, json, time

HOME = os.path.expanduser("~")
LEDGER = os.path.join(HOME, ".claude", "time-tracking", "timelog.jsonl")
PRICING = os.path.join(HOME, ".claude", "time-tracking", "pricing.json")


def hms(s):
    s = int(round(s))
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    if h: return f"{h}h {m}m"
    if m: return f"{m}m {sec}s"
    return f"{sec}s"


def load_rows():
    if not os.path.exists(LEDGER):
        return []
    out = []
    for l in open(LEDGER, encoding="utf-8"):
        l = l.strip()
        if not l:
            continue
        try:
            out.append(json.loads(l))
        except Exception:
            pass
    return out


def load_schedules():
    try:
        P = json.load(open(PRICING, encoding="utf-8"))
        return sorted(P.get("schedules", []), key=lambda s: s.get("effective_from", ""))
    except Exception:
        return []


def sched_for(scheds, date_str):
    if not scheds:
        return None
    elig = [s for s in scheds if s.get("effective_from", "") <= (date_str or "9999")]
    return (elig or scheds)[-1]


def cost_with(sched, r):
    if not sched:
        return 0.0
    rates = (sched.get("models") or {}).get(r.get("model", ""), sched.get("default") or {})
    return (
        r.get("in_tokens", 0)      * rates.get("input", 0)
      + r.get("out_tokens", 0)     * rates.get("output", 0)
      + r.get("cache_read", 0)     * rates.get("cache_read", 0)
      + r.get("cache_write_5m", 0) * rates.get("cache_write_5m", 0)
      + r.get("cache_write_1h", 0) * rates.get("cache_write_1h", 0)
    ) / 1_000_000.0


def main():
    period = "week"
    show_billing = False
    for a in sys.argv[1:]:
        if a == "--billing":
            show_billing = True
        else:
            period = a

    rows = load_rows()
    if not rows:
        print("(empty ledger — nothing logged yet)")
        return
    scheds = load_schedules()
    current = scheds[-1] if scheds else None

    # ---- period filter (by local date in ts) -------------------------------
    today = time.strftime("%Y-%m-%d")
    if period == "today":
        keep = lambda d: d == today
        label = f"today ({today})"
    elif period == "all":
        keep = lambda d: True
        label = "all time"
    else:
        days = {"week": 7, "month": 30}.get(period)
        if days is None:
            try:
                days = int(period)
            except ValueError:
                days = 7
        cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - (days - 1) * 86400))
        keep = lambda d: d >= cutoff
        label = f"last {days} days ({cutoff} .. {today})"

    rows = [r for r in rows if keep(r.get("ts", "")[:10])]
    if not rows:
        print(f"(no entries for {label})")
        return
    rows.sort(key=lambda r: r.get("epoch", 0))

    sessions = {}
    for r in rows:
        sessions.setdefault(r.get("session", "?"), []).append(r)

    turns = [r for r in rows if r.get("category") == "turn_end" and "in_tokens" in r]
    prompts = [r for r in rows if r.get("category") == "prompt"]

    # ---- time: session span, agent turn time, turnaround -------------------
    session_span = 0.0
    agent_time = 0.0
    turnaround = 0.0
    for sid, evs in sessions.items():
        evs.sort(key=lambda r: r.get("epoch", 0))
        session_span += evs[-1]["epoch"] - evs[0]["epoch"]
        last_turn_end = None
        pending_prompt = None
        for e in evs:
            c = e.get("category")
            if c == "prompt":
                pending_prompt = e
                if last_turn_end is not None:
                    turnaround += max(0, e["epoch"] - last_turn_end)
            elif c == "turn_end":
                if pending_prompt is not None:
                    agent_time += max(0, e["epoch"] - pending_prompt["epoch"])
                    pending_prompt = None
                last_turn_end = e["epoch"]

    # ---- intervals by category --------------------------------------------
    by_cat = {}
    for r in rows:
        if r.get("kind") == "interval" and r.get("dur_s") is not None:
            by_cat[r.get("category", "?")] = by_cat.get(r.get("category", "?"), 0) + r["dur_s"]

    # ---- cost --------------------------------------------------------------
    def actual(r):
        if r.get("cost_usd") is not None:
            return r["cost_usd"]
        return cost_with(sched_for(scheds, r.get("ts", "")[:10]), r)
    act_total = sum(actual(r) for r in turns)
    today_total = sum(cost_with(current, r) for r in turns)
    cost_by_day, cost_by_proj, cost_by_model = {}, {}, {}
    for r in turns:
        a = actual(r)
        cost_by_day[r.get("ts", "")[:10]] = cost_by_day.get(r.get("ts", "")[:10], 0) + a
        cost_by_proj[r.get("project", "?")] = cost_by_proj.get(r.get("project", "?"), 0) + a
        cost_by_model[r.get("model", "?")] = cost_by_model.get(r.get("model", "?"), 0) + a

    # ---- tokens ------------------------------------------------------------
    tin = sum(r.get("in_tokens", 0) for r in turns)
    tout = sum(r.get("out_tokens", 0) for r in turns)
    tcr = sum(r.get("cache_read", 0) for r in turns)
    tcw = sum(r.get("cache_write_5m", 0) + r.get("cache_write_1h", 0) for r in turns)
    tws = sum(r.get("web_search", 0) for r in turns)
    twf = sum(r.get("web_fetch", 0) for r in turns)

    # ---- effort ------------------------------------------------------------
    eff_tagged, eff_assumed, eff_untagged = {}, {}, 0
    for p in prompts:
        e = p.get("effort")
        if not e:
            eff_untagged += 1
        elif p.get("effort_certain"):
            eff_tagged[e] = eff_tagged.get(e, 0) + 1
        else:
            eff_assumed[e] = eff_assumed.get(e, 0) + 1

    def fmt_money_map(m):
        return ", ".join(f"{k} ${v:.2f}" for k, v in sorted(m.items(), key=lambda x: -x[1]))

    # ---- print -------------------------------------------------------------
    W = 64
    print("=" * W)
    print(f" CLAUDE ACCOUNTING REPORT - {label}")
    print("=" * W)
    print(f"\nSESSIONS\n  {len(sessions)} sessions | {len(turns)} turns | {len(prompts)} prompts")
    print(f"  session wall-clock (incl. idle): {hms(session_span)}")

    print("\nTIME")
    print(f"  agent working time (sum of turns): {hms(agent_time)}")
    print(f"  your time between turns (idle/read): {hms(turnaround)}")
    if by_cat:
        print(f"  logged task intervals: {hms(sum(by_cat.values()))}")
        for k, v in sorted(by_cat.items(), key=lambda x: -x[1]):
            print(f"     {k:10} {hms(v)}")
    else:
        print("  logged task intervals: (none)")

    print("\nCOST  (reference value)")
    print(f"  Actual ${act_total:.2f}    Today ${today_total:.2f}")
    if len(cost_by_day) > 1:
        print("  by day:   " + ", ".join(f"{d} ${v:.2f}" for d, v in sorted(cost_by_day.items())))
    print(f"  by project: {fmt_money_map(cost_by_proj)}")
    print(f"  by model:   {fmt_money_map(cost_by_model)}")

    print("\nTOKENS")
    print(f"  in {tin:,}  out {tout:,}  cache_read {tcr:,}  cache_write {tcw:,}")
    if tws or twf:
        print(f"  web: {tws} searches, {twf} fetches")

    print("\nEFFORT  (in-band tags)")
    if eff_tagged or eff_assumed:
        order = ["low", "medium", "high", "extra", "max", "ultracode"]
        seen = set(eff_tagged) | set(eff_assumed)
        for lvl in order + sorted(seen - set(order)):
            if lvl in seen:
                print(f"  {lvl:10} {eff_tagged.get(lvl,0)} tagged + {eff_assumed.get(lvl,0)} assumed")
        print(f"  untagged:  {eff_untagged}")
    else:
        print(f"  (no effort tags yet — write 'effort: <level>' in a message)   untagged: {eff_untagged}")

    if show_billing:
        modes = [r.get("billing_mode") for r in load_rows()
                 if r.get("category") == "session_start" and r.get("billing_mode")]
        mode = modes[-1] if modes else "unknown"
        print("\nBILLING")
        if mode == "subscription":
            print("  subscription — $ figures are REFERENCE VALUE (API-equivalent), not money billed.")
            print("  See the Anthropic Console for actual charges and subscription/overage split.")
        elif mode == "api_key":
            print("  api_key — $ approximates pay-as-you-go charges at list prices.")
        else:
            print("  unknown — interpret $ as reference value.")
    print()


if __name__ == "__main__":
    main()
