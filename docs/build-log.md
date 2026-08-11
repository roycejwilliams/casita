---
icon: lucide/notebook-pen
---

# Build Log: The Conversational Preference Agent

`CONTRIBUTING.md` asks for more than a diff: pick something, and explain why
you chose it. This page is that explanation, kept as a sequence of decisions
rather than a single retrospective summary, so the reasoning behind each turn
is visible, not just the final shape.

## 1. Reading the existing structure first

Before proposing anything, the read was: ranking already has two layers
(`rank.py` fixed constants, `llm.py`'s prompt-based policy), one existing
preference channel (`casita analyze-prefs`, vote-driven, human-reviewed,
never auto-applied), and one unused hook — `PhotoReview` fields
(`light_quality`, `view_quality`, `condition_quality`, `outdoor_visible`)
captured by photo evaluation but never read by scoring. That gap — captured
but never scored — became the opening for this feature instead of a
from-scratch idea.

## 2. Starting point: a voice feature, borrowed from Co

The first framing was direct: build something like the voice/conversational
work already shipped at Co (CoPatible) — extract structured user context from
free conversation instead of a form. An iMessage guide agent, mirroring Co's
Sendblue channel, was floated alongside it.

**Cut: the iMessage agent.** It would have meant new channel infrastructure
(a messaging integration) for an interview-scoped demo that already has a
credentials-free constraint to protect. Keeping the feature to one mechanism
with two input modes (voice, text) kept it testable without new
infrastructure — see [Getting Started](getting-started.md) and the demo's
credentials-free contract in `AGENTS.md`.

## 3. Correction: this had to be live voice, not text-only

An early pass scoped the feature down to text-only, reasoning that voice
needs credentials a credentials-free demo can't assume. That was a
misread — the ask was specifically a *live* voice agent. The fix wasn't to
drop voice; it was to make text the fallback mode, not the feature: `--voice`
(spoken, needs an STT/TTS key) and `--intake` (typed, Gemini only) became two
input modes feeding one pipeline, so the feature is credential-testable via
`--intake` without ever being text-only by design.

## 4. Reframe: emotional context, layered — not replacing the gate

The scope sharpened again: "give people their dream house based on their
emotional context." That's a bigger claim than logistics extraction, and it
raised the real risk — that emotional fit could quietly override the
household's hard requirements (no small dogs, laundry, parking).

The resolution mirrors a rule already implicit in the codebase's ranking
policy ("hard requirements win, soft preferences break ties"): emotional fit
layers on top of the logistics gate as an additive bonus, and the gate stays
absolute. See
[Layering In Emotional Fit](how-it-works/preferences.md#layering-in-emotional-fit).
This is also why the `PhotoReview` fields from step 1 mattered — they were
already the right shape for scoring emotional fit; nothing new needed to be
captured, just read.

## 5. Splitting mechanism from inspiration

Documentation started as one page. It split in two on purpose: `how-it-works/preferences.md`
documents *how the mechanism works* (inputs, extraction, scoring, what's
ephemeral vs. durable) — the same register as every other `how-it-works` page.
The *why this exists* narrative — the Co comparison, what was cut and why,
what "dream house from emotional context" means — belongs in `README.md`,
next to the rest of the project's own framing, not mixed into subsystem docs.

## 6. Routing: reading the doc's own extension note before proposing one

`routing.md`'s own "Ways This Could Go Further" already named two things: make
anchor sets easier to inspect, and explain why a route matters on the card —
explicitly "without changing the personal assumptions."

The first instinct was to let the agent accept new, user-named anchors
("near my gym in the Mission") during conversation. That was cut on
inspection: it would mean geocoding, a live Maps Routes API dependency beyond
what's cached, and a changed anchor set — the exact thing the doc's note
scoped out. The narrower fit was better: the agent narrates routing data
`walk.py` already computes, grounding its replies in real anchor minutes, and
can list the fixed anchor set on request. No new anchors, no new API surface.
See [Narrating the Route, Not Just Scoring It](how-it-works/preferences.md#narrating-the-route-not-just-scoring-it).

## 7. Two more processes needed narration, not silence

Two existing processes were quietly making judgment calls without saying so:
routing (already scoped in step 6) and deduplication. `dedup.py`'s `_merge()`
folds duplicate listings from different sources together, filling empty
fields one-way — but when two sources *disagree* (different price, different
dog policy) it just picked one and moved on. That's the opposite of "guide
the person through finding a home" — it's hiding a judgment call instead of
surfacing it.

The fix: `_merge()` now also records disagreements into
`raw["source_conflicts"]` (field, both values, both sources) instead of
silently resolving them. The agent can then narrate the disagreement — "Zillow
lists this at $3,200, Redfin at $3,400" — rather than showing one number with
no context. `deduplicate_db()` (the DB-persisted path) was left untouched on
purpose; the conflict-recording only lives in the in-memory `_merge()` path
this feature reads from.

## 8. From "voice-capable" to voice-to-voice, mid-build

The feature had been built as text-first with voice as a stretch mode. That
got corrected: the agent needed to actually sympathize and hold a spoken
conversation, not just accept spoken input and print a table. Two decisions
followed:

- **Push-to-talk over always-listening.** Simpler capture boundary (Enter to
  start, Enter to stop), no voice-activity-detection dependency, and it keeps
  the turn-taking explicit — good for a demo a stranger (an interviewer) is
  trying for the first time.
- **The call has to end itself.** A live phone-style demo that never hangs up
  is a bad demo. `--voice` now stops on any of: a silent/blank turn, a spoken
  sign-off ("that's all," "I'm good," "stop," "done"), the model itself
  judging it has what it needs (`ready_to_wrap_up` on the structured turn
  output), or a 15-minute hard cap. The first turn also asks a guided
  question naming the fields the agent actually needs (beds, parking,
  laundry, trail/beach access, feel) rather than an open-ended "tell me
  about yourself" — the extraction schema is fixed, so the question should
  point at it instead of hoping free conversation covers it.

Both `--intake` and `--voice` were also converted from single-shot extraction
to a real multi-turn loop mid-build, after re-checking against the original
intent: the first intake was always supposed to be conversational, re-running
extraction against the *full* accumulated transcript each turn, not a single
question-and-done exchange.

## 9. Bringing it into the browser: text first, live, no new flag

The last extension was making the conversation live in the actual product
surface instead of the terminal — a reviewer should be able to open the
rendered site and try it themselves, not take a CLI transcript on faith.

- **Text, not voice, in the browser.** Browser-based voice (mic capture,
  streaming audio) is real additional surface — permissions, streaming, a
  different code path from the terminal's `sounddevice` capture. Scoped out
  for now as a fast-follow; the in-browser mode reuses the exact same
  `extract_preferences` / rerank / `explain_listing` functions `--intake`
  already calls, just behind a small `POST /api/chat` endpoint instead of a
  terminal loop.
- **No new CLI flag.** `/chat/` is always served alongside the rest of the
  static site — there's no reason to gate a same-page chat UI behind a flag
  the way `--voice` is gated behind an optional audio dependency.
- **Problem solving: a real cross-thread SQLite bug.** The static file
  server's `ThreadingMixIn` runs every request, including `POST /api/chat`,
  on its own thread. `walk.py`'s route-cache connection was opened on the
  main thread during initial render with SQLite's default
  `check_same_thread=True`, so the first chat message crashed with "SQLite
  objects created in a thread can only be used in that same thread." Fixed
  with `check_same_thread=False` plus a `threading.RLock()` around the cache
  read/write functions. Found and confirmed via a live `curl` reproduction
  before and after the fix, not just inferred from reading the code.

## 10. "Would it show the correct houses?" — and a bucket-priority bug that answer surfaced

Manual end-to-end testing (live Gemini credentials, a real Vertex AI
project) exposed a gap step 9 left open: `--intake`/`--voice` re-ranked and
printed to the terminal, but `_render_site()` ran afterward from the
untouched fixture order — the browser never actually reflected what was
said. Fixed by having `_run_intake()`/`_run_voice()` return their last
successful `(profile, ranked)` pair, and threading it into `_render_site()`
as an optional `session_result` that reorders the rendered listings.

That fix immediately surfaced a real bug, not a hypothetical one: reordering
purely by session preference score put a **landlord-declined listing in the
#1 feature card** — confirmed live, by rendering the actual site and reading
the HTML, not just by inspecting code. The session re-rank has no concept of
`rank.py`'s durable buckets (active pipeline → favorites → ranked → new →
filtered → eliminated); a stated preference alone was enough to rank a
listing the household already passed on above ones still genuinely in play.

The fix was a new shared helper, `session_prefs.durable_bucket()`, that
classifies a listing into the same tier `rank.rank()` would — reusing
`rank.py`'s exported `ELIMINATED_STATUSES`/`PIPELINE_STRENGTH` constants
rather than duplicating its scoring, and without editing `rank.py` itself.
Both the site render and `/chat/`'s live re-rank now sort by
`(durable_bucket, session_score)`, so a preference can only reorder listings
*within* their existing tier — it can move a listing up among its peers, but
it can never pull an eliminated listing above a live one or bury an active
lead. Fixing the render path this way surfaced that `/chat/`'s
`handle_message()` (step 9) had the identical latent bug already shipped —
its top-10 chat recommendations were sorted by preference score alone too.
Fixed alongside it with the same helper, so both surfaces now share one
definition of "durable tier" instead of two independent, driftable copies.

## 11. Filtering the grid, not just reordering it

A live `--intake` run showed why a subtle reorder wasn't enough: two
unrelated active-pipeline listings dominated the top of a 143-listing page,
so a stated preference (asked to be near Baker Beach) was invisible without
scrolling. The first instinct was a small "matched to what you said"
highlight strip layered next to the main grid — additive, doesn't turn a
soft preference into a second gate. But for what this demo needs to prove
to an interviewer at a glance, that wasn't compelling. A filter is what
actually reads as "it worked."

Went with filtering, scoped to avoid its two real failure modes: an
empty-feeling page, and losing track of real leads. `_render_site()` now
shows a firm top 10 of what matched the session's stated preference, plus
every active pipeline/favorite listing regardless of score — those are the
household's real to-do list, not something a passing conversation should
hide — with a banner stating the filter plainly. If nothing matched closely
enough, it falls back to the full reordered list instead of showing next to
nothing.

Verifying this live surfaced the declined-listing bug from entry 10 again,
in a different spot: the terminal's own ranked table, its explanations, and
`generate_spoken_reply()` were still sorting off the raw, status-blind
session score, meaning `--voice` could have spoken a landlord-declined
listing aloud as a top recommendation. Fixed by applying
`session_prefs.durable_bucket()` to `_run_intake()`/`_run_voice()`'s own
ranked list before printing or generating a reply, so the terminal, the
spoken answer, and the site now all agree.

## 12. Voice felt slow, and RANK_MODEL was carrying too much

`--voice` makes three sequential Gemini calls per turn: transcribe and
extract, generate the spoken reply, then synthesize speech. Two of the
three — transcribe/extract and the reply — were hardcoded to `RANK_MODEL`
(`gemini-3.1-pro-preview`), the same model `rank_listings()`/
`review_photos()` use for real, quality-sensitive durable ranking. Timed
live against the actual Vertex project rather than assumed:
`gemini-3.1-pro-preview` averaged 6.5-9.7s per call; `gemini-2.5-flash`
averaged 1.3-1.8s, confirmed first to handle both text and audio input
correctly before switching anything over.

Rather than repointing `RANK_MODEL` itself — which would've also changed
`rank_listings()`/`review_photos()`'s model, a different concern with
different quality needs — added a dedicated `CASITA_VOICE_MODEL` env var,
defaulting to `gemini-2.5-flash`. Voice latency and durable ranking quality
can now be tuned independently instead of trading off against each other.

## What this leaves out, on purpose

- No iMessage bot (step 2).
- No persistent, cross-session profile store — Co has one; this is
  session-ephemeral by design (see `preferences.md`'s Before/After table).
- No new anchors or geocoding (step 6).
- No auto-applied policy changes — a stated preference stays session-scoped
  and never writes `_RANK_SYSTEM`, preserving the same reviewability
  guarantee `analyze-prefs` already has (see [Learning From Votes](how-it-works/learning.md)).
- No browser-based voice (step 9) — `/chat/` is text-only; live spoken
  conversation still only exists in the terminal via `--voice`.

Each cut has the same shape: a real capability Co already has, deliberately
not ported, because it would add persistent state or new infrastructure this
feature doesn't need to make its point.
