#!/bin/sh
# statusline wrapper — forwards the statusline JSON on stdin to
# statusline-limits.py (which captures rate_limits into the timelog ledger and
# prints the status text). stdout must pass through; stderr is silenced so a
# python error can never corrupt the statusline.
python "$HOME/.claude/statusline-limits.py" 2>/dev/null || echo "limits: n/a"
exit 0
