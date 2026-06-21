#!/bin/sh
# timelog status-line renderer — called by the statusLine command wired in
# ~/.claude/settings.json. Forwards the statusLine event JSON on stdin to
# timelog-statusline.py, which prints ONE status-bar line (this session's last
# effort + model). Pure display; always exits 0 so it can't break the status bar.
python "$HOME/.claude/timelog-statusline.py" 2>/dev/null
exit 0
