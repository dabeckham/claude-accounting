#!/bin/sh
# timelog hook-side logger — called by the global SessionStart / UserPromptSubmit
# / Stop hooks (wired in ~/.claude/settings.json). Forwards the hook event JSON
# on stdin to timelog-hook.py, which appends ONE event line to the ledger. Must
# write nothing to stdout (no context injection) and always exit 0 (never block).
#
# $1 = event category: session_start | prompt | turn_end
python "$HOME/.claude/timelog-hook.py" "$1" 2>/dev/null
exit 0
