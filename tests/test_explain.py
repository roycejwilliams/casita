from casita import session_prefs
from casita.llm import EmotionalProfile, LogisticsProfile, PreferenceProfile
from casita.models import Listing
from casita.walk import BEACHES


def _listing(key: str, **overrides) -> Listing:
    defaults = dict(
        source="manual",
        source_id=key,
        url="",
        title=f"listing {key}",
        price=3000,
        beds=2,
        baths=1,
        dog_policy="dogs_ok",
    )
    defaults.update(overrides)
    return Listing(**defaults)


def _profile(**logistics_overrides) -> PreferenceProfile:
    logistics = dict(
        wants_trail_or_beach_access=False,
        needs_in_unit_laundry=False,
        needs_parking=False,
        min_beds=None,
        notes="",
    )
    logistics.update(logistics_overrides)
    return PreferenceProfile(
        logistics=LogisticsProfile(**logistics),
        emotional=EmotionalProfile(
            light_preference="no_preference",
            view_preference="no_preference",
            condition_preference="no_preference",
            wants_outdoor_space=False,
            desired_feeling="",
        ),
    )


def test_explain_listing_near_beach_with_preference_cites_anchor_and_minutes():
    listing = _listing("near-beach")
    profile = _profile(wants_trail_or_beach_access=True)
    beach = BEACHES[0]
    walk_map = {(listing.key, beach.name): 8}

    text = session_prefs.explain_listing(listing, profile, walk_map)

    assert beach.name in text
    assert "8" in text
    assert "beach access" in text


def test_explain_listing_no_conflicts_says_nothing_about_conflicts():
    listing = _listing("clean")
    profile = _profile()

    text = session_prefs.explain_listing(listing, profile, None)

    assert "disagree" not in text
    assert "Heads up" not in text


def test_explain_listing_with_source_conflict_names_field_and_values():
    listing = _listing(
        "conflicted",
        raw={
            "source_conflicts": [
                {"field": "price", "zillow": 3000, "craigslist": 3200},
            ]
        },
    )
    profile = _profile()

    text = session_prefs.explain_listing(listing, profile, None)

    assert "zillow" in text
    assert "craigslist" in text
    assert "price" in text
    assert "3,000" in text or "3000" in text
    assert "3,200" in text or "3200" in text


def test_explain_listing_no_match_produces_empty_string():
    listing = _listing("plain")
    profile = _profile()

    text = session_prefs.explain_listing(listing, profile, None)

    assert text == ""


def test_explain_listing_no_beach_access_flag_omits_routing_even_if_near():
    listing = _listing("near-beach-no-want")
    profile = _profile(wants_trail_or_beach_access=False)
    beach = BEACHES[0]
    walk_map = {(listing.key, beach.name): 8}

    text = session_prefs.explain_listing(listing, profile, walk_map)

    assert text == ""
