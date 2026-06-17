# Effort — why it's tagged manually, not auto‑detected

The reasoning‑**effort** level you select in the Claude desktop UI (Opus 4.8: `low · medium · high · extra · max · ultracode`) is one of the most useful things to track for cost analysis — and one of the few that **cannot be captured automatically**. This doc records the investigation so nobody repeats it.

## What was checked (and why each failed)

1. **Hook payloads** — `UserPromptSubmit`/`Stop` events contain `session_id`, `cwd`, `prompt`, `transcript_path`. No effort field.
2. **The session transcript** — contains `model` and full `usage`, but **no** effort/budget field. Extended‑thinking blocks carry only an encrypted `signature`, not the level.
3. **The desktop app's storage** — the embedded claude.ai IndexedDB *does* contain an `effort_level` field, but it **statically reads `low` regardless of the actual selection**. Verified against ground truth: the user was on **High** (prior turn **Ultra**) while the freshly‑written blob still said `low`. So the real dropdown value lives only in the app's in‑memory state and is sent with the API request — it is never written to disk in a readable form.

**Conclusion:** the only place the true value exists in readable form is the **outbound API request body** (`output_config.effort`). Reading it requires intercepting the request (see *The relay option* below).

## The working capture: in‑band tagging

Because effort can't be read, the user supplies it in‑band — accurate because it's their own words:

- Write `effort: <level>` (or `effort=<level>`) anywhere in a message.
- The `prompt` hook parses it → `effort` + `effort_certain: true`, and **remembers** it in `~/.claude/.timelog-last-effort`.
- An **untagged** message **inherits** the last tagged level with `effort_certain: false` (assumed) — so you don't retype it every turn.
- No tag and no prior → no `effort` field (never guessed).
- `ultra` is accepted as an alias for `ultracode`.

In reporting, treat `effort_certain: false` as accurate (the value held from the last explicit tag) but keep it distinguishable from explicitly tagged turns.

## The relay option (automatic, but heavier — not enabled by default)

`ANTHROPIC_BASE_URL` is honored by the Claude Code stack. Pointing it at a **localhost HTTP relay** that forwards to `https://api.anthropic.com` lets the relay read `output_config.effort` off each `/v1/messages` request — the *true* per‑turn value, automatically, **with no root CA** (the app→relay hop is plain localhost HTTP; relay→Anthropic is HTTPS).

Trade‑offs that keep this opt‑in:

- The relay sees **all** traffic, including the auth token and full conversation content.
- It becomes a **dependency in the API path** — if it's down, the app can't reach the API. **Provide a one‑command revert of `ANTHROPIC_BASE_URL`** before relying on it.
- It must be transparently pass‑through (streaming/tool‑use) or it breaks the app, so it needs careful hardening and a fresh‑session test.

This is tracked as an open enhancement issue rather than shipped, because the in‑band tag already captures effort with zero infrastructure and no risk to the app.
