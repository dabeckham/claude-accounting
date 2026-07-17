#!/usr/bin/env python
"""Shared turn-accounting logic for the time-tracking ledger.

This is the single source of truth for *how a turn's token usage is summed and
priced*. Both the live Stop hook (`timelog-hook.py`) and the historical backfill
(`backfill-from-transcripts.py`) import it, so a reconstructed turn is counted
byte-for-byte the same way the hook counted it live.

A "turn" is the slice of a transcript from one real user prompt up to (but not
including) the next. A real user prompt is an entry with type == "user" that does
NOT carry a "toolUseResult" key (tool-result messages also have type "user").

Usage is summed over the *assistant* messages in that slice, DEDUPED BY
`requestId`: a single streamed API response is written to the transcript as
multiple assistant records that share one requestId, each carrying the same
usage snapshot. Counting every record multi-counts real API calls (measured
~2.6x on live data). We keep one usage snapshot per requestId (last record
wins — the finalized value) and count it once, reading the top-level usage
fields directly.
"""
import os, json, time


def is_prompt_boundary(entry):
    """True if `entry` is a real user prompt (a turn boundary), not a tool result."""
    return entry.get("type") == "user" and "toolUseResult" not in entry


def last_turn_start(rows):
    """Index of the last real user prompt in `rows` (0 if none). This is the
    boundary the live Stop hook uses when it sums the just-finished turn."""
    for i in range(len(rows) - 1, -1, -1):
        if is_prompt_boundary(rows[i]):
            return i
    return 0


def iter_turn_slices(rows):
    """Yield (start, end) index pairs, one per real user prompt, splitting `rows`
    into turns at every prompt boundary. The slice rows[start:end] holds the
    prompt and the assistant messages that answered it."""
    bounds = [i for i, e in enumerate(rows) if is_prompt_boundary(e)]
    for j, start in enumerate(bounds):
        end = bounds[j + 1] if j + 1 < len(bounds) else len(rows)
        yield start, end


def summarize_turn(turn_rows):
    """Sum one turn's token usage, counting each real API call exactly once.

    Streaming writes a single API response as several assistant records sharing
    one `requestId`, each with the same usage snapshot; summing them all inflates
    the counts ~2.6x. We group the turn's assistant records by requestId, keep
    the last snapshot per request (the finalized value), and accumulate once per
    request, so each real API call is counted exactly once. Returns the
    token/model fields the live hook records; `msgs` is the number of distinct
    API calls in the turn (0 when the slice holds none, so callers that drop
    empty turns can still check it)."""
    # Last usage snapshot per requestId, in first-seen order.
    per_req, order = {}, []
    models, thinking = set(), False
    for e in turn_rows:
        if e.get("type") != "assistant":
            continue
        m = e.get("message", {}) or {}
        if m.get("model"):
            models.add(m["model"])
        for c in (m.get("content") or []):
            if isinstance(c, dict) and c.get("type") == "thinking":
                thinking = True
        u = m.get("usage", {}) or {}
        if not u:
            continue
        # Dedupe key: requestId, then the message id, then a per-record unique
        # fallback (so an id-less record is still counted once, never collapsed).
        key = e.get("requestId") or m.get("id")
        if key is None:
            key = ("_noid", len(order))
        if key not in per_req:
            order.append(key)
        per_req[key] = u  # last record wins

    tin = tout = tcr = cw5 = cw1 = cc_total = ws = wf = 0
    for key in order:
        u = per_req[key]
        tin += u.get("input_tokens", 0) or 0
        tout += u.get("output_tokens", 0) or 0
        tcr += u.get("cache_read_input_tokens", 0) or 0
        cc_total += u.get("cache_creation_input_tokens", 0) or 0
        cc = u.get("cache_creation") or {}
        cw5 += cc.get("ephemeral_5m_input_tokens", 0) or 0
        cw1 += cc.get("ephemeral_1h_input_tokens", 0) or 0
        stu = u.get("server_tool_use", {}) or {}
        ws += stu.get("web_search_requests", 0) or 0
        wf += stu.get("web_fetch_requests", 0) or 0

    # If the split buckets are empty but a total was reported, attribute it to the
    # 5-minute bucket (the default cache TTL) so cost isn't undercounted.
    if cw5 == 0 and cw1 == 0 and cc_total > 0:
        cw5 = cc_total
    models.discard("<synthetic>")
    return {
        "model": sorted(models)[0] if len(models) == 1 else ",".join(sorted(models)),
        "in_tokens": tin,
        "out_tokens": tout,
        "cache_read": tcr,
        "cache_write_5m": cw5,
        "cache_write_1h": cw1,
        "web_search": ws,
        "web_fetch": wf,
        "used_thinking": thinking,
        "msgs": len(order),
    }


def load_schedules(pricing_path=None):
    """Return the pricing schedules sorted ascending by effective_from ([] on error)."""
    pricing_path = pricing_path or os.path.join(
        os.path.expanduser("~"), ".claude", "time-tracking", "pricing.json")
    try:
        P = json.load(open(pricing_path, encoding="utf-8"))
        return sorted(P.get("schedules", []), key=lambda s: s.get("effective_from", ""))
    except Exception:
        return []


def rate_for(sched, model):
    """Return the per-million-token rate dict for `model` from one schedule.

    Matches the exact model id first, then the LONGEST `models` key that is a
    prefix of the id, then falls back to the schedule `default`. The prefix step
    is what handles date-suffixed ids: the transcript reports
    `claude-haiku-4-5-20251001` while the schedule is keyed `claude-haiku-4-5`,
    and without it Haiku would silently fall through to the (Opus) default rate."""
    models = sched.get("models") or {}
    if model in models:
        return models[model]
    prefixes = [k for k in models if model.startswith(k)]
    if prefixes:
        return models[max(prefixes, key=len)]
    return sched.get("default") or {}


def price_turn(rec, schedules=None, date_str=None, pricing_path=None):
    """Stamp a turn's cost using the pricing schedule in effect on `date_str`
    (default today). Returns (cost_usd, pricing_from) or (None, None) on any
    problem — never raises. This is the immutable 'Actual' spend locked in at the
    prices that applied on the turn's own date."""
    try:
        scheds = schedules if schedules is not None else load_schedules(pricing_path)
        if not scheds:
            return (None, None)
        date_str = date_str or time.strftime("%Y-%m-%d")
        elig = [s for s in scheds if s.get("effective_from", "") <= date_str] or scheds
        sched = max(elig, key=lambda s: s.get("effective_from", ""))
        rates = rate_for(sched, rec.get("model", ""))
        cost = (
            rec.get("in_tokens", 0)      * rates.get("input", 0)
          + rec.get("out_tokens", 0)     * rates.get("output", 0)
          + rec.get("cache_read", 0)     * rates.get("cache_read", 0)
          + rec.get("cache_write_5m", 0) * rates.get("cache_write_5m", 0)
          + rec.get("cache_write_1h", 0) * rates.get("cache_write_1h", 0)
        ) / 1_000_000.0
        return (round(cost, 6), sched.get("effective_from"))
    except Exception:
        return (None, None)


# --- Per-session effort carry-forward -------------------------------------
# The effort/reasoning level can't be read from the API call or disk, so Don
# tags it in-band ("effort=high"). An untagged prompt inherits the last tagged
# level for the SAME session (Don moves between sessions constantly and their
# effort differs), marked effort_certain=false. State lives in one small JSON
# file keyed by the 8-char session id: { "3df7b1c9": "medium", ... }. Only
# sessions Don has actually tagged get a key; a brand-new/untagged session has
# no entry and stays unlabeled.

EFFORT_LEVELS = ("low", "medium", "high", "extra", "max", "ultracode")


def effort_state_path():
    return os.path.join(os.path.expanduser("~"), ".claude", ".timelog-last-effort.json")


def _load_effort_state():
    try:
        with open(effort_state_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def read_session_effort(sess):
    """Last tagged effort level for `sess`, or "" if the session was never tagged."""
    return _load_effort_state().get(sess, "")


def set_session_effort(sess, lvl):
    """Record `lvl` as the last tagged effort for `sess` (best-effort, never raises)."""
    try:
        d = _load_effort_state()
        d[sess] = lvl
        with open(effort_state_path(), "w", encoding="utf-8") as f:
            json.dump(d, f)
    except Exception:
        pass
