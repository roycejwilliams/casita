"""Session-scoped preference re-rank — layered on top of `rank.py`, never
replacing it. See docs/how-it-works/preferences.md.

This module imports `rank.score()` and adds an emotional/logistics-fit
BONUS for the current session only. `rank.py` itself stays untouched —
that's a documented promise in the design doc, not just a style choice.
"""
from .llm import PreferenceProfile
from .models import Listing
from .rank import ELIMINATED_STATUSES, PIPELINE_STRENGTH, score

# Bonus weights are deliberately small and additive-only — nudges, not a
# second gate. `rank.score()` returns -1000 for the no_dogs hard gate; the
# total bonus ceiling here (well under 100) can never rescue a gated-out
# listing or push it above a passing one.
_LIGHT_BONUS = 8
_VIEW_BONUS = 8
_CONDITION_BONUS = 6
_OUTDOOR_BONUS = 10
_TRAIL_BEACH_BONUS = 10
_LAUNDRY_BONUS = 6
_PARKING_BONUS = 6
_BEDS_BONUS = 6

# A trail/beach walk under this many minutes counts as "access" for the
# stated preference — matches the sweet-spot rank.py already uses.
_TRAIL_BEACH_MINUTES = 20


def _emotional_bonus(listing: Listing, profile: PreferenceProfile) -> int:
    e = profile.emotional
    bonus = 0
    if e.light_preference != "no_preference" and listing.light_quality == e.light_preference:
        bonus += _LIGHT_BONUS
    if e.view_preference != "no_preference" and listing.view_quality == e.view_preference:
        bonus += _VIEW_BONUS
    if e.condition_preference != "no_preference" and listing.condition_quality == e.condition_preference:
        bonus += _CONDITION_BONUS
    if e.wants_outdoor_space and listing.outdoor_visible:
        bonus += _OUTDOOR_BONUS
    return bonus


def _logistics_bonus(listing: Listing, profile: PreferenceProfile, walk_map: dict | None) -> int:
    lo = profile.logistics
    bonus = 0
    if lo.wants_trail_or_beach_access and walk_map is not None:
        from .walk import BEACHES, PRESIDIO_GATES, nearest
        near_trail = nearest(walk_map, listing.key, PRESIDIO_GATES)
        near_beach = nearest(walk_map, listing.key, BEACHES)
        if (near_trail and near_trail[1] <= _TRAIL_BEACH_MINUTES) or (
            near_beach and near_beach[1] <= _TRAIL_BEACH_MINUTES
        ):
            bonus += _TRAIL_BEACH_BONUS
    if lo.needs_in_unit_laundry and listing.laundry == "in-unit":
        bonus += _LAUNDRY_BONUS
    if lo.needs_parking and listing.parking and "no parking" not in listing.parking.lower() and listing.parking != "none":
        bonus += _PARKING_BONUS
    if lo.min_beds is not None and listing.beds and listing.beds >= lo.min_beds:
        bonus += _BEDS_BONUS
    return bonus


def preference_bonus(listing: Listing, profile: PreferenceProfile, walk_map: dict | None = None) -> int:
    """Additive nudge only, reading a listing's existing captured fields
    (light/view/condition/outdoor from `PhotoReview`, laundry/parking/beds
    from logistics) against the stated profile. Never a gate.
    """
    return _emotional_bonus(listing, profile) + _logistics_bonus(listing, profile, walk_map)


# Field-specific phrasing for `dedup.py`'s CONFLICT_FIELDS — each reads a
# little differently as a plain-English sentence.
_CONFLICT_LABELS = {
    "price": "price",
    "dog_policy": "dog policy",
    "parking": "parking",
    "laundry": "laundry",
}


def _fmt_conflict_value(field: str, value) -> str:
    if field == "price" and isinstance(value, (int, float)):
        return f"${value:,.0f}"
    return str(value)


def _conflict_sentence(conflict: dict) -> str:
    """One flagging sentence for a single `source_conflicts` entry, e.g.
    `{"field": "price", "zillow": 3000, "craigslist": 3200}` ->
    "Heads up: zillow and craigslist disagree on price — $3,000 vs $3,200.
    Worth confirming."
    """
    field = conflict.get("field")
    sources = [(k, v) for k, v in conflict.items() if k != "field"]
    if not field or len(sources) < 2:
        return ""
    (src_a, val_a), (src_b, val_b) = sources[0], sources[1]
    label = _CONFLICT_LABELS.get(field, field)
    va, vb = _fmt_conflict_value(field, val_a), _fmt_conflict_value(field, val_b)
    return f"Heads up: {src_a} and {src_b} disagree on {label} — {va} vs {vb}. Worth confirming."


def _routing_sentence(listing: Listing, profile: PreferenceProfile, walk_map: dict | None) -> str:
    """Ground a routing claim in the SAME lookups `llm._walk_summary` uses —
    `walk.nearest`/`walk.minutes_to` against the passed-in `walk_map` for SF,
    or the Marin drive-time path via `walk.is_marin`/
    `walk.populate_drive_for_marin`. No new routing computation, no live API
    calls beyond what those helpers already cache.

    Only speaks up when `wants_trail_or_beach_access` is true AND there's a
    nearby trail or beach — otherwise silent rather than fabricating a match.
    """
    if not profile.logistics.wants_trail_or_beach_access:
        return ""

    from .walk import BEACHES, TRAILS, is_marin, nearest, populate_drive_for_marin

    if is_marin(listing):
        drive_map = populate_drive_for_marin([listing])
        if not drive_map:
            return ""
        beach = nearest(drive_map, listing.key, BEACHES)
        trail = nearest(drive_map, listing.key, TRAILS)
        verb = "drive"
    else:
        if walk_map is None:
            return ""
        beach = nearest(walk_map, listing.key, BEACHES)
        trail = nearest(walk_map, listing.key, TRAILS)
        verb = "walk"

    candidates = [c for c in (("beach access", beach), ("trail access", trail)) if c[1]]
    if not candidates:
        return ""
    label, (anchor, minutes) = min(candidates, key=lambda c: c[1][1])
    return f"{minutes} min {verb} to {anchor.name} — matches wanting {label}."


def explain_listing(
    listing: Listing,
    profile: PreferenceProfile,
    walk_map: dict | None = None,
) -> str:
    """Ground the agent's response in real data for one listing: cite the
    actual anchor minutes behind a stated trail/beach preference, and flag
    any cross-source disagreement recorded by `dedup._merge()`. Returns a
    short multi-sentence string, or "" if there's nothing groundable to say.
    See docs/how-it-works/preferences.md, "Narrating the Route, Not Just
    Scoring It."
    """
    sentences = []
    routing = _routing_sentence(listing, profile, walk_map)
    if routing:
        sentences.append(routing)
    for conflict in listing.raw.get("source_conflicts", []):
        sentence = _conflict_sentence(conflict)
        if sentence:
            sentences.append(sentence)
    return " ".join(sentences)


def rerank_with_profile(
    listings: list[Listing],
    walk_map: dict | None,
    profile: PreferenceProfile,
) -> list[tuple[Listing, int, int]]:
    """Session-scoped re-rank: `rank.score()` unchanged, plus an additive
    preference bonus for this session only.

    Returns (listing, base_score, bonus) sorted descending by
    base_score + bonus. Does not mutate `rank.py`, the listings, or any
    stored llm_rank/llm_severity.
    """
    scored = [
        (L, score(L, walk_map), preference_bonus(L, profile, walk_map))
        for L in listings
    ]
    return sorted(scored, key=lambda t: t[1] + t[2], reverse=True)


def durable_bucket(
    listing: Listing,
    status_map: dict[str, str] | None = None,
    vote_scores: dict[str, int] | None = None,
) -> int:
    """Classify a listing into the same durable tier `rank.rank()` sorts by
    — active pipeline, favorites, ranked, new, filtered, eliminated —
    reusing its exported constants (`ELIMINATED_STATUSES`,
    `PIPELINE_STRENGTH`) rather than duplicating its scoring.

    Any UI that reorders listings around a session's stated preferences
    (the rendered site after `--intake`/`--voice`, `/chat/`'s live re-rank)
    should sort by this first and the preference score second, so a session
    can only reorder listings *within* a tier — it can never pull an
    eliminated listing above a live one or bury an active pipeline lead.
    """
    status_map = status_map or {}
    vote_scores = vote_scores or {}
    status = status_map.get(listing.key)
    if status in ELIMINATED_STATUSES:
        return 3
    if PIPELINE_STRENGTH.get(status, 0):
        return -2
    if vote_scores.get(listing.key, 0) > 0:
        return -1
    if listing.llm_severity == "filtered" or (listing.llm_rank or 0) >= 9000:
        return 2
    if listing.llm_rank is None:
        return 1
    return 0
