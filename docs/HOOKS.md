# Hooks — how the automatic capture works

Claude Code fires user‑defined **hooks** at lifecycle points. This project wires three of them, all pointing at one script, `timelog-hook.sh`, which forwards the hook's JSON (delivered on **stdin**) to `timelog-hook.py`.

| Hook | Argument passed | What it records |
|---|---|---|
| `SessionStart` (matcher `startup\|resume\|compact`) | `session_start` | a `session_start` event; `desc` = the source (startup/resume/compact) |
| `UserPromptSubmit` | `prompt` | a `prompt` event; `desc` = a snippet of your message; parses an `effort:` tag (carry‑forward is **per session** — see [EFFORT.md](EFFORT.md)) |
| `Stop` | `turn_end` | a `turn_end` event; parses the transcript tail for model + token usage |

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

## Disabling / scoping

The hooks live in **user‑level** `~/.claude/settings.json`, so they apply to every project. To pause logging, remove (or comment out by relocating) the `hooks` block — it's a one‑line‑per‑hook change. To scope to a single project, move the block into that project's `.claude/settings.json` instead.
