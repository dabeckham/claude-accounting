# Hooks — how the automatic capture works

Claude Code fires user‑defined **hooks** at lifecycle points. This project wires three of them, all pointing at one script, `timelog-hook.sh`, which forwards the hook's JSON (delivered on **stdin**) to `timelog-hook.py`.

| Hook | Argument passed | What it records |
|---|---|---|
| `SessionStart` (matcher `startup\|resume\|compact`) | `session_start` | a `session_start` event; `desc` = the source (startup/resume/compact) |
| `UserPromptSubmit` | `prompt` | a `prompt` event; `desc` = a snippet of your message; parses an `effort:` tag (carry‑forward is **per session** — see [EFFORT.md](EFFORT.md)) |
| `Stop` | `turn_end` | a `turn_end` event; parses the transcript tail for model + token usage |

A fourth lifecycle point, **`statusLine`**, is wired to a *separate* script — see [Status line](#status-line) below.

## Why a wrapper script + a Python file

The hook event JSON arrives on **stdin**. A naïve `python - <<'PY'` heredoc would hijack stdin (Python would read the *script* instead of the event), so `timelog-hook.sh` calls a real file:

```sh
python "$HOME/.claude/timelog-hook.py" "$1"   # stdin stays the hook event
exit 0                                          # never block the turn
```

The hook writes **nothing to stdout** (so it never injects context) and always exits `0` (so a logging hiccup can never break a turn).

## Where tokens and model come from

Token usage and the model id are **not** in the hook payload — they live only in the **session transcript** (`transcript_path`, provided to the `Stop` hook). For `turn_end`, the script:

1. Reads only the **last ~2 MB** of the transcript (transcripts grow to tens of MB; the current turn is at the end).
2. Walks back to the last real user prompt (a `type:"user"` entry **without** a `toolUseResult` key — tool results are also `type:"user"`).
3. Sums usage across every assistant message in that turn, including each tool round‑trip's `iterations[]` (each is a billed API call), so `cache_read` can be very large on long sessions.
4. Records `model`, `in_tokens`, `out_tokens`, `cache_read`, `cache_write_5m`, `cache_write_1h`, `web_search`, `web_fetch`, `used_thinking`, `msgs`.

### Path normalization (Windows)

Claude Code may pass `transcript_path` as a native Windows path (`C:\…`) or an MSYS path (`/c/Users/…`). Native Windows Python can't `stat` the `/c/` form, so the script converts `/c/Users/…` → `C:/Users/…` when the literal path doesn't resolve.

## Performance

Each turn spawns one short‑lived `sh` + `python`. The `Stop` hook reads a bounded 2 MB tail, so cost stays roughly constant regardless of total transcript size. Append is a single `>>` write of one JSON line (<4 KB → atomic).

## Status line

Claude Code's **`statusLine`** config runs a command on every render and shows its
stdout in a line beneath the input box. This project wires it to
`timelog-statusline.sh` → `timelog-statusline.py`, which prints this session's
current effort + model, e.g.:

```
● Last effort: medium · Opus 4.8
```

- The session id and `model.display_name` come from the statusLine payload on **stdin**.
- The effort is read from the same per‑session map the `prompt` hook writes
  (`~/.claude/.timelog-last-effort.json`), so it always reflects *this* session — an
  unlabeled session shows a dim dot and `Last effort: —`.
- The dot is colored by level via ANSI 256‑color codes; output is written as **UTF‑8
  bytes** because the glyphs (`●`, `·`) don't exist in a Windows `cp1252` console.
- It's pure display: nothing is sent to the model, nothing is appended to the ledger,
  and it always exits `0` so it can't break the status bar.

Wire it by adding a `statusLine` block to `~/.claude/settings.json` (see
[`config/settings.example.json`](../config/settings.example.json)).

## Disabling / scoping

The hooks live in **user‑level** `~/.claude/settings.json`, so they apply to every project. To pause logging, remove (or comment out by relocating) the `hooks` block — it's a one‑line‑per‑hook change. To scope to a single project, move the block into that project's `.claude/settings.json` instead.
