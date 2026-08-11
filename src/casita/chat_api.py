"""Business logic for the third preference-agent mode: a live, in-browser
TEXT chat at `/chat/` (see docs/how-it-works/preferences.md). Kept separate
from the HTTP plumbing in `__init__.py`'s `do_POST` so it's unit-testable
without a real server — mirrors `_run_intake()`'s loop shape (always
re-extract on the FULL cumulative transcript, not just the newest turn) but
returns JSON-able dicts instead of printing to the terminal.

Session state is a single module-level transcript — this is a single-user
local personal demo, so no per-browser-session bookkeeping is needed. The
frontend calls `POST /api/chat/reset` once on page load so a fresh browser
tab doesn't inherit a stale transcript from a previous visitor.

`handle_message()`'s return shape — the `/chat/` page's JS depends on this
exactly, so keep field names stable:

    {"error": "..."}   on any failure to extract or re-rank, or

    {
        "reply": str,          # llm.generate_spoken_reply()'s plain text
        "profile": {...},      # PreferenceProfile.model_dump() (logistics + emotional)
        "ranked": [
            {
                "key": str, "title": str | None, "hood": str | None,
                "price": int | None, "image_url": str | None,
                "dog_policy": str | None,
                "base": int, "bonus": int, "total": int,
                "explanation": str,   # "" if nothing groundable to say
            },
            ...   # top 10, best first
        ],
    }
"""
from . import llm, session_prefs, storage, walk

_transcript_parts: list[str] = []


def reset_session() -> None:
    _transcript_parts.clear()


def handle_message(message: str) -> dict:
    """Append `message` to the session transcript, re-extract preferences
    from the full cumulative transcript, re-rank, and return a JSON-able
    dict for the frontend. Never raises.
    """
    _transcript_parts.append(message)
    full_transcript = "\n".join(_transcript_parts)

    try:
        profile = llm.extract_preferences(full_transcript)
    except Exception as e:
        profile = None
        print(f"  chat extract err: {str(e)[:120]}")
    if profile is None:
        return {
            "error": "couldn't extract a preference profile "
            "(check Gemini credentials) — try again in a moment."
        }

    try:
        with storage.connect() as conn:
            listings = storage.active_listings(conn)
            status_map = storage.status_map(conn)
            vote_scores = storage.vote_scores(conn)
        walk_map = walk.populate_for(listings)
        ranked = session_prefs.rerank_with_profile(listings, walk_map, profile)
        # Reorder within rank()'s durable buckets only — see
        # session_prefs.durable_bucket() — so a chat preference can never
        # surface a declined/eliminated listing as a live recommendation,
        # or bury an active pipeline lead.
        ranked.sort(
            key=lambda t: (
                session_prefs.durable_bucket(t[0], status_map, vote_scores),
                -(t[1] + t[2]),
            )
        )

        # Same pattern as __init__.py's _print_explanations(): grounded
        # route/conflict narration for the top few, skipping listings with
        # nothing groundable to say — kept to 5, not the full top-10, so
        # generate_spoken_reply() (which only looks at the top 2) has what
        # it needs without extra Gemini-facing text to build for nothing.
        explanations: list[str] = []
        for L, _, _ in ranked[:5]:
            text = session_prefs.explain_listing(L, profile, walk_map)
            if text:
                explanations.append(text)

        reply = llm.generate_spoken_reply(message, profile, ranked, explanations)
    except Exception as e:
        print(f"  chat rerank err: {str(e)[:120]}")
        return {"error": "something went wrong building the session re-rank — try again."}

    ranked_out = [
        {
            "key": L.key,
            "title": L.title or L.address or L.key,
            "hood": L.hood,
            "price": L.price,
            "image_url": L.image_url,
            "dog_policy": L.dog_policy,
            "base": base,
            "bonus": bonus,
            "total": base + bonus,
            "explanation": explanations[i] if i < len(explanations) else "",
        }
        for i, (L, base, bonus) in enumerate(ranked[:10])
    ]

    return {
        "reply": reply,
        "profile": profile.model_dump(),
        "ranked": ranked_out,
    }
