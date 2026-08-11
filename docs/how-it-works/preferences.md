---
icon: lucide/sliders-horizontal
---

# Preferences

## Existing Structure

Ranking already has two layers, and both currently encode one fixed,
hardcoded set of assumptions rather than anything per-user:

- `src/casita/rank.py` — `score()` sorts on fixed constants: dog policy,
  walk-to-Presidio, walk-to-beach, neighborhood bonus, beds/baths, laundry,
  parking. These numbers don't move at runtime.
- `src/casita/llm.py` — `_RANK_SYSTEM` is a large prompt string encoding the
  same assumptions in prose (two large dogs, SF/Marin geography, trail/beach
  access, bakery preferences, aesthetics-is-a-tiebreaker, etc.), sent to
  Gemini on every `rank_listings()` call.

Preference **does** already adjust, but through one narrow, existing channel:
the vote feedback loop (see [Learning From Votes](learning.md)). Up/pass
votes accumulate in SQLite; `casita analyze-prefs` reads them, compares
revealed behavior against `_RANK_SYSTEM`, and prints proposed contradictions
and new rules. It never writes the policy itself. A human reads the proposal,
hand-edits `_RANK_SYSTEM`, and commits — a durable, intentional change to the
household's real policy.

Separately, [Photo Evaluation](photo-eval.md) already extracts `light_quality`,
`view_quality`, `condition_quality`, `outdoor_visible`, and `visual_summary`
for every listing via Gemini vision. Today those fields only feed the card,
the detail page, and the share blurb — `rank.py`'s `score()` never reads any
of them. That's the gap this feature closes.

## Added Feature: A Conversational Preference Agent

Add a second, separate mechanism that operates at a different layer:
**session personalization**, not policy authorship. Someone talks — or types
— for a minute, and sees the sanitized demo listings re-ranked around what
they said, without touching the household's durable policy.

- **Three input modes, one pipeline.** `casita demo --voice` (spoken),
  `casita demo --intake` (typed, terminal), and the live in-browser chat at
  `/chat/` (typed, always served — no flag needed) all feed the same
  extraction → re-rank → explain pipeline downstream of "understand the
  input." Base `uv run casita demo` is unchanged.
  - `--intake` and `--voice` are multi-turn loops in the terminal: each turn
    re-extracts against the *full* accumulated transcript, not just the
    latest utterance, so a later turn can add to or refine what came before.
    Once the conversation ends, the site render that follows uses that
    session's re-rank — the browser opens already reflecting what was said,
    not the durable order (see "Showing It, Not Just Saying It" below).
  - `--voice` is genuinely voice-to-voice — push-to-talk capture
    (`voice.py`), Gemini transcribes and extracts in one multimodal call,
    then replies with a spoken, empathetic response (native Gemini audio
    output, no separate TTS vendor). The first turn asks a guided opening
    question covering the fields the agent needs (beds, parking, laundry,
    trail/beach access, and how the place should feel). The call ends
    itself — no separate "hang up" step — on any of: a blank/silent turn, a
    spoken sign-off ("that's all," "I'm good," "stop," "done"), the model
    judging it has what it needs (`ready_to_wrap_up`), or a 15-minute cap.
    Transcription/extraction and the spoken reply run on `CASITA_VOICE_MODEL`
    (default `gemini-2.5-flash`) rather than the heavier `RANK_MODEL` — kept
    on its own knob since these calls are latency-sensitive (someone's
    waiting to hear a reply) in a way durable ranking/photo-review aren't.
  - `/chat/` is the same extraction/re-rank/explain pipeline served live in
    the browser: a chat log, a running profile panel, and the re-ranked
    listings all update in place as you type, via `POST /api/chat` (and
    `POST /api/chat/reset` on page load). No voice yet — text only.
- **Extraction now produces two things, not one:**
  1. **Logistics** — the same shape `rank.py` already scores: dog policy,
     walk-to-trail/beach, beds/baths, laundry, parking.
  2. **Emotional profile** — what the conversation reveals about how someone
     wants to *feel* in the place: e.g. "craves natural light," "wants a
     calm retreat, not a party layout," "needs an outdoor connection."
     "Dream house from emotional context" is the housing-domain version of
     what Co already does with `emotional_state` and `goals` in its own
     profile extraction.
- **Reviewable, not just spoken back.** The transcript and both extracted
  pieces are always surfaced, never applied silently — the same
  reviewability instinct as `analyze-prefs` never auto-applying a proposal,
  adapted to a mechanism with no human-review gate to cross. `/chat/` takes
  this furthest: transcript, profile, and re-ranked listings render live in
  the browser, in place, as you type. `--intake` and `--voice` print the same
  transcript/profile/table information to the terminal during the
  conversation, then hand their final (profile, ranked) state to the site
  render that follows — so the browser opens already reordered around what
  was said, just not updating live mid-conversation the way `/chat/` does.
- **Ephemeral, not durable**: nothing here touches `_RANK_SYSTEM` or
  `analyze-prefs`. Scoped to one session's view of the fixture data.
- **Credentials**: all three modes need Gemini, same as every other
  LLM-backed command in this repo — no separate STT/TTS vendor. `--voice`
  transcribes and extracts in one multimodal Gemini call and speaks back
  using Gemini's native audio output; `--intake` and `/chat/` are text-only
  and need nothing beyond Gemini. `--intake` is the version that's actually
  testable with a scripted transcript and a mocked Gemini client (no audio
  hardware required).

## Layering In Emotional Fit

The emotional profile **layers on top of logistics — it never replaces the
gate.** Concretely, scoring for the session becomes two passes:

1. **Logistics gate + score — unchanged.** `rank.py`'s existing logic runs
   exactly as it does today: `no_dogs` still returns `-1000` and is
   eliminated outright; walk bonuses, beds/baths, laundry, and parking score
   exactly as before. Nothing about this pass changes.
2. **Emotional-fit bonus — new, additive.** For listings that survive the
   gate, compare the extracted emotional profile against that listing's
   already-captured `PhotoReview` fields — `light_quality`, `view_quality`,
   `condition_quality`, `outdoor_visible`, `visual_summary` — and add a bonus
   for a match (e.g. "craves natural light" + `light_quality="abundant"`).
   This bonus is added to, never substituted for, the logistics score.

The gate stays absolute: nothing emotional can rescue a `no_dogs` listing or
outrank it into contention. Emotional fit only reorders among listings that
already pass logistics — the same "hard requirements win, soft preferences
break ties" structure `_RANK_SYSTEM` already uses for the durable policy,
just applied session-side.

## Showing It, Not Just Saying It

After `--intake`/`--voice` finish, `casita demo` re-renders the site around
the session's re-rank instead of the durable order. This took two real
fixes, both found by testing the feature live rather than trusting the code
on read-through:

- **A stated preference can never promote a declined listing or bury an
  active lead.** The first version reordered the full 143-listing set by
  session score alone, which put a landlord-declined listing in the #1
  feature card — its bonus for beach access said nothing about whether the
  household could actually rent it. Fixed with
  `session_prefs.durable_bucket()`, a small helper that classifies each
  listing into the same tier [Ranking](ranking.md)'s `rank()` already sorts
  by — active CRM pipeline, then favorites, then ranked/new/filtered, with
  eliminated listings pinned at the bottom — reusing `rank.py`'s own
  exported `ELIMINATED_STATUSES`/`PIPELINE_STRENGTH` constants rather than
  duplicating its judgment. A preference can only reorder listings *within*
  a tier now, never across one. `rank.py` itself is never modified or
  called differently.
- **The terminal and the spoken reply had the same blind spot.** That
  bucket-aware sort only touched the site render at first.
  `_run_intake()`/`_run_voice()`'s own printed table, explanations, and —
  worse, for `--voice` — the spoken reply were still ranking off the raw,
  status-blind session score, meaning `--voice` could genuinely recommend a
  declined listing out loud. Fixed by applying the same
  `durable_bucket()` sort before printing or generating a reply, so the
  terminal, the spoken answer, and the rendered site now always agree.

The rendered site also filters, not just reorders. Showing all 143
listings lightly reshuffled made a stated preference nearly invisible — a
two-slot reorder is easy to miss scanning a full page. `_render_site()` now
shows a firm top 10 of what actually matched, plus any active
pipeline/favorite listings regardless of whether they scored a preference
bonus (those are real household leads, not something one session's spoken
preference should hide). A banner on the page states the filter plainly —
"Showing your top 10 matches + N active pipeline/favorite listings out of
143" — and if nothing matched closely enough to filter meaningfully, it
falls back to showing everything reordered instead of an almost-empty page.

This is recomputed from scratch on every `demo` run and never writes
anywhere — the fixture, `llm_rank`, and vote state stay untouched. `/chat/`
uses the same `durable_bucket()` sort on its own top-10 recommendations,
for the same reason: a chat preference should never surface a listing
that's already dead.

## Narrating the Route, Not Just Scoring It

[Routing](routing.md)'s own "Ways This Could Go Further" already names this
gap: make anchor sets easier to inspect, and explain why a route matters on
the card, without changing the personal assumptions. The agent is a natural
place to do the second one, in language rather than UI:

- **Grounded replies.** When the agent explains why a listing ranked where
  it did, it cites the actual `walk.py` figures against whatever anchor the
  stated preference points to — "8 minutes to Baker Beach" when someone said
  they want beach access — instead of a bare number on the card with no
  context.
- **Anchor-set visibility.** Asked "what are you measuring against?", the
  agent can list the fixed curated anchors it's scoring — trails, beaches,
  bakeries, the Ferry Building. This surfaces the existing anchor set; it
  does not add to it.

Deliberately out of scope: no new anchors, no geocoding, no live Maps Routes
API calls beyond what's already cached. The agent explains routing that
`walk.py` already computed — it doesn't compute new routing.

## Before / After

| | Today | With the conversational agent |
| --- | --- | --- |
| How preference is stated | Only by voting on individual listings | Also by talking or typing to the agent, live — in the browser (`/chat/`) or the terminal (`--intake`/`--voice`) |
| Logistics gate | Fixed constants in `rank.py` | Same constants, same gate — unchanged |
| Emotional/vibe fit | Captured by `PhotoReview`, never scored | Layered on top as a bonus, after the gate |
| Why a route matters | A number on the card, no context | Agent narrates it against what you said, using the same cached `walk.py` data |
| What it affects | `_RANK_SYSTEM`, via human-applied edits | The current session's view of `fixtures/demo.sqlite` only |
| Durable policy change? | Yes — the point of the vote loop | No — ephemeral, resets next session |
| Transparency | N/A | Transcript + both extracted profiles always surfaced; `/chat/` updates the page live, in place, as you type; `--intake`/`--voice` print to the terminal during the conversation, then the site re-renders — filtered to a banner-labeled top 10 + active leads — once the conversation ends |
| New dependencies | — | Gemini (existing) for all three modes; native Gemini audio output for `--voice` only |
| Testable without credentials/audio? | N/A | Yes, via `--intake` with a scripted transcript + mocked Gemini client |

## Ways This Could Go Further

The agent could eventually feed the durable loop too — treating a stated
preference, logistical or emotional, as another kind of proposal for
`analyze-prefs` to surface. That would need the same reviewability guarantee
the vote loop already has: proposed, never auto-applied. Left out here to
keep the two mechanisms cleanly separate until there's a real reason to
connect them.
