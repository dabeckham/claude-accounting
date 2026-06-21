#!/usr/bin/env python
"""Claude Code statusLine renderer for the time-tracking ledger.

Reads the statusLine event JSON on stdin and prints ONE line for the status bar:

    ● Last effort: medium · Opus 4.8

The dot is colored by effort level (green→red ramp). "Last effort" is THIS
session's most-recent tagged level, read from the same per-session state the
prompt hook writes (timelog_core.read_session_effort). A session that has never
been tagged shows a dim dot and "Last effort: —". The model name comes from the
statusLine payload's model.display_name. Pure display — never sent to the model,
never written to the ledger; always exits 0 so it can't break the status bar.
"""
import sys, json, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import timelog_core as core

# ANSI 256-color codes for the dot, ramped low→high. None means "not yet tagged".
DOT_COLOR = {
    "low": 34,        # green
    "medium": 226,    # yellow
    "high": 208,      # orange
    "extra": 202,     # dark orange
    "max": 196,       # red
    "ultracode": 201, # magenta (hottest)
    None: 240,        # dim grey — no effort recorded for this session
}


def colored_dot(level):
    code = DOT_COLOR.get(level, 240)
    return "\033[38;5;{}m●\033[0m".format(code)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    sess = (str(data.get("session_id") or ""))[:8]
    model = ""
    m = data.get("model")
    if isinstance(m, dict):
        model = str(m.get("display_name") or m.get("id") or "")

    level = core.read_session_effort(sess) or None
    label = level if level else "—"

    parts = ["{} Last effort: {}".format(colored_dot(level), label)]
    if model:
        parts.append(model)
    out = " · ".join(parts)
    # Force UTF-8: the status glyphs (●, ·) and ANSI codes must survive a Windows
    # console whose default stdout encoding is cp1252, which can't encode them.
    try:
        sys.stdout.buffer.write(out.encode("utf-8"))
    except Exception:
        sys.stdout.write(out.encode("ascii", "replace").decode("ascii"))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
