# Casita

[![Documentation](https://img.shields.io/badge/docs-casita-0b6e4f?style=for-the-badge)](https://matin.github.io/casita/)

Casita is a personal rental-search tool published as a public repo.

It started as a small script for a time-boxed San Francisco rental search with
two large dogs: scrape Zillow, Craigslist, Zumper, and Redfin; enrich the
listings; rank them; and render a static page that was easier to review than
four open browser tabs.

This is not a product or service. It is published as-is, under MIT, as a
personal-use codebase for an interview loop. The interesting part is what a
candidate chooses to improve.

## Demo

The demo is credentials-free and uses a sanitized SQLite fixture with cached
route times and precomputed LLM enrichment.

```bash
uv sync
uv run playwright install chromium
uv run casita demo
```

Then open <http://127.0.0.1:8765/>.

The demo does not scrape, call Vertex, deploy to Firebase, read GCS, or call the
Google Maps Routes API. It does use Playwright's local Chromium browser to
render Open Graph preview images from listing photos and facts. Live `search` /
`enrich` / `publish` paths still exist for private use and are controlled by
environment variables; see `.env.example`.

## What It Does

- Scrapes active rental listings from Zillow, Craigslist, Zumper, and Redfin.
- Normalizes listing facts into SQLite.
- Classifies dog policy and enriches details from listing pages.
- Uses Gemini for fact extraction, photo review, share blurbs, and ranking.
- Computes walking and driving times to curated SF / Marin anchors.
- Renders a static, mobile-friendly site with index and detail pages.
- Records votes and passes so future ranking can learn from reviewer feedback.

The domain assumptions are intentionally personal: large dogs, San Francisco
walkability, Marin driving context, trails, beaches, and good bakeries nearby.
That is the point of a personal tool.

## What I Added: A Conversational Preference Agent

The domain assumptions above are fixed — hardcoded into `rank.py`'s scoring
constants and the ranking prompt in `llm.py`. The one existing way to shift
them is voting listing-by-listing and waiting for `casita analyze-prefs` to
notice a pattern worth hand-editing into policy. There was no way to just
say what you want.

I added a second, separate mechanism: a conversational agent, reachable by
voice (`casita demo --voice`) or text (`casita demo --intake`), that talks
to you for a minute and re-ranks the demo listings around what you said —
both your logistics ("no small dogs, need in-unit laundry") and, further,
your emotional context ("I want somewhere that feels like a calm retreat,
lots of natural light"). It's scoped as session personalization, not policy
authorship: it never touches the durable `_RANK_SYSTEM` policy or the vote
loop, and the logistics gate stays absolute no matter how well a listing
matches the emotional read. See
[`docs/how-it-works/preferences.md`](docs/how-it-works/preferences.md) for
the full mechanism, and the before/after of what it does and doesn't change.

**Where it came from.** I'd built a close cousin of this at Co
(CoPatible) — a voice-and-text concierge that extracts a structured profile
(`life_chapters`, `emotional_state`, `goals`, `blockers`) from free
conversation rather than a form, using one shared persona across a live
voice call (Hume EVI) and iMessage (Sendblue), spoken replies via ElevenLabs
TTS, and a persistent Postgres profile. "Give someone their dream house
based on their emotional context" is the housing version of that same
instinct. What's different here is scale and stakes: Co is a multi-channel,
multi-user, persistent-state production system. This is sized for what an
interview take-home should actually ship — ephemeral, single-session, no new
infrastructure beyond what the repo already has, plus one credential for
real voice. No iMessage bot, no persistent profile store, no durable policy
writes; those were explicit cuts, not oversights.

## Docs

The [documentation site](https://matin.github.io/casita/) explains the systems
without turning them into assigned tasks. To run it locally instead:

```bash
uv run zensical serve
```

Start at `docs/index.md`, or run `uv run zensical build` to generate the site.

## Checks

```bash
make check
```

This compiles the Python modules, runs the pytest suite, runs the public leak
validator, builds the docs, builds the Python package artifacts, and checks
that the CLI imports.

## Contributing

Read `CONTRIBUTING.md`. The short version: fork the repo, pick something you
think makes Casita better, and explain why you chose it.
