# Casita

A personal rental search tool for a household with two large dogs, published as-is for an interview loop.

## Demo

The base demo needs no credentials. It runs off a sanitized SQLite fixture with cached route times and precomputed rankings already baked in.

```bash
uv sync
uv run playwright install chromium
uv run casita demo
```

Open <http://127.0.0.1:8765/>.

The conversational agent needs real Gemini credentials to actually respond, whichever way you reach it (see "Environment setup" below):

```bash
uv run casita demo --intake   # type what you want
uv run casita demo --voice    # say what you want, also needs a mic
```

`/chat/` is also live on the running demo site (click "chat" on the page), no flag needed, but it calls the same live Gemini extraction under the hood, so it needs credentials too.

Without credentials, `--intake`, `--voice`, and `/chat/` all fail cleanly with an error instead of crashing. Only the bare `casita demo` with no flags is fully credential-free.

## What it does

- Scrapes active listings from Zillow, Craigslist, Zumper, and Redfin.
- Normalizes everything into one SQLite schema.
- Uses Gemini to extract facts, review photos, write share blurbs, and rank listings.
- Computes walking and driving times to curated SF and Marin anchors: trails, beaches, bakeries.
- Renders a static site with an index page and a detail page per listing.
- Tracks up and down votes so a human can review revealed preference and hand-edit the ranking policy.
- Talks or types with you about what you want (voice, typed terminal, or live browser chat) and shows the listings that actually match, for that session only.

## Architecture

```mermaid
flowchart TD
    subgraph Input["Three ways in"]
        V["--voice<br/>push-to-talk"]
        T["--intake<br/>typed, terminal"]
        C["/chat/<br/>typed, browser, live"]
    end

    subgraph Pipeline["One shared pipeline"]
        E["Extract<br/>logistics + emotional profile"]
        R["Re-rank<br/>rank.py gate unchanged,<br/>plus a session bonus"]
        X["Explain<br/>routing + conflict narration"]
    end

    subgraph Output["Where it shows up"]
        TERM["Terminal table,<br/>plus a spoken reply for --voice"]
        SITE["Rendered site,<br/>top matches + active leads"]
        LIVE["/chat/ page,<br/>updates in place"]
    end

    V --> E
    T --> E
    C --> E
    E --> R --> X
    X --> TERM
    X --> SITE
    X --> LIVE
```

Three input modes feed the same extraction, re-rank, and explain pipeline. What you get back depends on how you talked to it: a printed table and a spoken reply for `--voice`, a re-rendered page for `--voice`/`--intake`, or a live-updating page for `/chat/`.

## Voice mode

`casita demo --voice` is a real voice conversation, not text input with a voice wrapper on top. Here's what happens on each turn:

1. Press Enter, say what you want, press Enter again to stop. This is push-to-talk, not always-on listening. It keeps the turn boundary explicit and needs no voice activity detection.
2. The recorded audio, plus a text summary of everything said in earlier turns, goes to Gemini in one multimodal call. Gemini transcribes the audio and extracts a structured preference profile (dog policy, laundry, parking, minimum beds, and how the person wants the place to feel) in that same call. There's no separate speech-to-text step.
3. The listings get re-ranked using that profile, layered on top of the existing scoring (see "How it works" below).
4. Gemini writes a short spoken reply grounded in the ranked results, then speaks it back using its own native audio output. No separate text-to-speech vendor.
5. The conversation keeps going until one of four things happens: a turn comes back silent, you say something like "that's all" or "stop", the model decides it already has enough to work with, or fifteen minutes pass.

The first turn asks a specific opening question (beds, parking, laundry, trail or beach access, how you want it to feel) instead of an open "tell me about yourself," since the extraction schema is fixed and the question should point straight at it.

## How it works

Ranking already had two layers before this feature: a scoring function with fixed constants (`rank.py`), and an LLM ranking pass using a big prompt written around one household's preferences (`llm.py`). Neither of those changed.

The conversational agent adds a third layer that only runs for the current session: extract what was said, add it as a bonus on top of the existing score, and never let it override the hard gate. A listing with no dogs allowed is still a hard no, no matter how well it otherwise matches what someone said about wanting good light.

The agent also respects the same priority the rest of the site already uses. A listing already declined by a landlord, or one actively being pursued in the CRM pipeline, keeps that status no matter what gets said in one conversation. A stated preference can move things around inside a tier. It can't rescue a dead lead or bury an active one.

After `--intake`/`--voice` finish, the site doesn't just reorder, it filters. Showing all the listings loosely reshuffled made a stated preference nearly impossible to notice, so the render now shows a firm top 10 of what matched, plus every active pipeline or favorited listing regardless of score, with a banner on the page explaining exactly what got filtered and why. `/chat/` works differently: it doesn't touch the homepage grid at all, it shows its own live-updating top 10 in the chat page itself.

More detail lives in [`docs/how-it-works/preferences.md`](docs/how-it-works/preferences.md) and the full build history in [`docs/build-log.md`](docs/build-log.md).

## Tech stack

- Python and Click for the CLI
- SQLite for storage, no external database
- Pydantic for structured LLM outputs: preference profiles, extracted facts, rankings
- Gemini via Vertex AI for extraction, ranking, photo review, and voice
- `sounddevice` for local mic capture and playback in `--voice`
- Playwright for scraping and rendering Open Graph preview images
- Static HTML, CSS, and JS for the site, no frontend framework
- Google Maps Routes API for live route times, with a cached offline fallback

## Environment setup

The base demo needs nothing. `uv run casita demo` runs off a committed fixture and never calls a live API. Everything below is only for live search, ranking, or the conversational agent with real Gemini.

1. Get the `gcloud` CLI if you don't have it:

   ```bash
   brew install --cask gcloud-cli
   ```

   (or use the installer at <https://cloud.google.com/sdk/docs/install>)

2. Pick a GCP project (existing or new) and turn on the Vertex AI API for it:

   ```bash
   gcloud services enable aiplatform.googleapis.com --project=YOUR_PROJECT_ID
   ```

3. Authenticate the client this app actually uses:

   ```bash
   gcloud auth application-default login
   ```

   If you get a warning about the quota project not matching, run:

   ```bash
   gcloud auth application-default set-quota-project YOUR_PROJECT_ID
   ```

4. Copy the env file and set your project:

   ```bash
   cp .env.example .env
   ```

   - `CASITA_GCP_PROJECT`: your project ID (or number, both work)
   - `CASITA_VOICE_MODEL`: model used for `--voice`'s transcription and replies, defaults to a fast one
   - `GOOGLE_MAPS_API_KEY`: optional, only needed for live route calculations

   The rest of the variables are documented inline in `.env.example`.

That's it. `casita demo --intake`, `--voice`, and `/chat/` will all call live Gemini once `CASITA_GCP_PROJECT` is set and you're authenticated.
