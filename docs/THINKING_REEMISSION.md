# Thinking re-emission — the economics of making reasoning persistent

Extended-thinking models emit two kinds of tokens per turn: the **reasoning** (the "thinking"
block) and the **answer** (the visible reply). By default the reasoning is *ephemeral* — it is
billed once, used to produce the answer, and then dropped. **Re-emitting** that reasoning into the
visible reply changes its lifetime, not its count, and that single change has a measurable cost
profile worth understanding before you turn it on.

This doc records what re-emission actually does to the token ledger, so the tradeoff is a decision
rather than a surprise.

## The realization that started it

The hidden reasoning is not sealed away in some separate system. For the duration of a turn it
sits in the **same context window** as everything else — so you can simply **ask the model to
re-emit it**, and the otherwise-invisible thinking prints right out. That's the whole "aha":
hidden is not gone, it's one request away. From there it's a half-step to a standing arrangement —
*whenever you finish a thinking block, re-emit it before continuing* — which makes the model's work
inspectable on demand. (The one honest constraint: only the *current* turn's reasoning is
recoverable, and only while it's still in context; if the harness has already dropped it, what
comes back is a flagged reconstruction, not the original.)

The narrative version of this discovery — including *why* it surfaced from chasing down one odd
word the model had produced — is the field-notes article
[`asking-for-the-hidden-tokens.html`](asking-for-the-hidden-tokens.html). This doc is the
accounting half: now that you *can* pull those tokens out on every turn, **what does it cost?**

## What "re-emission" means

A turn can be configured to copy its own thinking-block tokens into the *visible* output before
continuing with the answer — so the reasoning becomes readable in the transcript instead of hidden.
On long turns that re-enter thinking several times (e.g. after a tool result brings new
information), each block is re-emitted as it closes, interleaved with the work.

The useful question for accounting is: **does this duplicate tokens, and where does the cost land?**

## The key fact: thinking is normally ephemeral

In the Anthropic Messages API, a turn's thinking tokens are generated and **billed as output**
when produced. On *subsequent* turns, prior assistant thinking blocks are **not retained as input** —
the API strips them from the replayed history (the documented exception is thinking that is part of
an assistant turn containing tool use, which is preserved *within* that logical turn to keep the
reasoning chain intact). So in the baseline case:

- Reasoning costs **output tokens once**, on the turn that produced it.
- On every later turn it costs **zero** — it has already evaporated from the window.

> ⚠️ **Verify against the ledger, don't take this on faith.** The cross-turn stripping above is
> documented API behavior, but harness-level details (how Claude Code packs tool-use turns,
> compaction, caching) can shift exactly *when* a block leaves the window. The
> [time-tracking ledger](../README.md) is the instrument: compare `cache_read` growth across a few
> re-emission-ON vs OFF turns and let the numbers settle it. This project exists precisely to make
> that measurable.

## What re-emission changes: ephemeral → persistent

When the reasoning is copied into the *visible* reply, that text becomes part of the permanent
assistant message — which **is** replayed as input on every following turn. Re-emission therefore
does not "count everything twice." It **converts tokens that would have vanished into tokens that
persist for the rest of the session.** The cost shows up in two distinct places:

1. **Transient, this turn** — the hidden block and its visible copy briefly coexist, so the
   re-emitted content is generated roughly twice as output. A one-time, small bump.
2. **Cumulative, every later turn** — the persisted copy is re-read as input on all subsequent
   turns. With prompt caching this is a `cache_read` (0.1× the input rate) rather than a fresh
   input bill, plus a one-time cache write to land it — but it never drops back to zero the way the
   ephemeral original would have.

The dominant long-run term is therefore **`cache_read` × (persisted tokens) × (number of future
turns the block survives)** — and on long agentic sessions `cache_read` is already the largest line
on the bill (see [COST.md → "A note on magnitude"](COST.md)).

## A worked example

Using the Opus 4.8 schedule from [`config/pricing.json`](../config/pricing.json) — input `$5.00`,
output `$25.00`, cache-write-1h `$10.00`, cache-read `$0.50` per million tokens — for a single
**500-token** thinking block:

| Cost component | When | Re-emission OFF | Re-emission ON |
|---|---|--:|--:|
| Generate the reasoning (output) | turn produced | $0.01250 | $0.01250 |
| Generate the visible copy (output) | turn produced | — | $0.01250 |
| Cache-write the persisted copy (1h) | turn produced | — | $0.00500 |
| Re-read as input, per later turn (cache_read) | each future turn | $0 | $0.00025 |
| **…over 100 subsequent turns** | cumulative | **$0** | **$0.02500** |

So for one modest block the long-run difference is on the order of a few cents — trivial in
isolation. The catch is **accretion**: with re-emission ON, *every* turn's reasoning persists, so
the per-turn `cache_read` base climbs steadily for the whole session instead of resetting. Multiply
the table by dozens of blocks across hundreds of turns and it becomes a real, if modest, line item —
and, more importantly, it inflates the context window.

## The second-order cost: faster compaction

Independent of dollars, persisted reasoning **fills the context window faster**. A window that would
have shed each turn's thinking now carries all of it forward, so the session reaches its compaction
threshold sooner. Compaction itself costs a summarization pass and loses fidelity. On a long working
session, hitting that wall early is often a bigger practical cost than the cache-read pennies.

## Why this surfaces a deeper point about sampling

Re-emission is also a window onto how the model's output is conditioned. Each visible token is drawn
from a distribution conditioned on **everything above it — including the hidden reasoning.** An
observer reconstructing that distribution from the *visible* tokens alone is working from a partial
view of the prompt and will systematically mis-estimate it: a token that is astronomically rare
*unconditionally* (its marginal probability) can be the near-deterministic choice *locally* once the
hidden context is taken into account. Re-emission closes that gap by making the conditioning
readable — at the ledger cost described above. The visibility is the product; the persistence is the
bill.

## Recommendation

- **Default OFF.** Keep reasoning ephemeral on normal and long working sessions, where window
  headroom and `cache_read` growth matter most.
- **Turn it ON deliberately** when you specifically want to read or audit how a turn reached its
  answer — debugging a decision, teaching, or inspecting model behavior — and accept the modest,
  accreting cost for that visibility.
- **Let the ledger arbitrate.** If you want the real magnitude rather than the model above, measure
  `cache_read` and context growth across ON vs OFF turns. Test, don't theorize.
