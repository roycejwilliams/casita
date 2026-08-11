from casita import session_prefs
from casita.llm import EmotionalProfile, LogisticsProfile, PreferenceProfile
from casita.models import Listing


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


def _profile(**emotional_overrides) -> PreferenceProfile:
    emotional = dict(
        light_preference="no_preference",
        view_preference="no_preference",
        condition_preference="no_preference",
        wants_outdoor_space=False,
        desired_feeling="",
    )
    emotional.update(emotional_overrides)
    return PreferenceProfile(
        logistics=LogisticsProfile(
            wants_trail_or_beach_access=False,
            needs_in_unit_laundry=False,
            needs_parking=False,
            min_beds=None,
            notes="",
        ),
        emotional=EmotionalProfile(**emotional),
    )


def test_rerank_with_profile_light_match_ranks_above_nonmatch():
    matching = _listing("bright", light_quality="abundant")
    nonmatching = _listing("dim", light_quality="dim")
    profile = _profile(light_preference="abundant")

    ranked = session_prefs.rerank_with_profile([nonmatching, matching], None, profile)

    order = [L.key for L, _, _ in ranked]
    assert order == [matching.key, nonmatching.key]


def test_rerank_with_profile_no_dogs_listing_never_outranks_passing_listing():
    no_dogs = _listing(
        "no-dogs",
        dog_policy="no_dogs",
        light_quality="abundant",
        view_quality="panoramic",
        condition_quality="high-end",
        outdoor_visible="private fenced backyard",
        laundry="in-unit",
        parking="attached garage",
        beds=4,
    )
    passing = _listing(
        "passing",
        dog_policy="dogs_ok",
        light_quality="dim",
        view_quality="blocked",
        condition_quality="needs-work",
        beds=1,
    )
    # Profile matches every quality field the no_dogs listing has, so it
    # earns the maximum possible bonus — it should still rank last.
    profile = PreferenceProfile(
        logistics=LogisticsProfile(
            wants_trail_or_beach_access=False,
            needs_in_unit_laundry=True,
            needs_parking=True,
            min_beds=3,
            notes="",
        ),
        emotional=EmotionalProfile(
            light_preference="abundant",
            view_preference="panoramic",
            condition_preference="high-end",
            wants_outdoor_space=True,
            desired_feeling="",
        ),
    )

    ranked = session_prefs.rerank_with_profile([no_dogs, passing], None, profile)

    order = [L.key for L, _, _ in ranked]
    assert order == [passing.key, no_dogs.key]
    no_dogs_entry = next(t for t in ranked if t[0].key == no_dogs.key)
    assert no_dogs_entry[1] == -1000


def test_preference_bonus_matches_emotional_and_logistics_fields():
    listing = _listing(
        "match",
        light_quality="abundant",
        outdoor_visible="fenced backyard",
        laundry="in-unit",
        beds=3,
    )
    profile = PreferenceProfile(
        logistics=LogisticsProfile(
            wants_trail_or_beach_access=False,
            needs_in_unit_laundry=True,
            needs_parking=False,
            min_beds=3,
            notes="",
        ),
        emotional=EmotionalProfile(
            light_preference="abundant",
            view_preference="no_preference",
            condition_preference="no_preference",
            wants_outdoor_space=True,
            desired_feeling="",
        ),
    )

    bonus = session_prefs.preference_bonus(listing, profile)

    assert bonus > 0
    assert bonus < 1000


def test_preference_bonus_no_match_is_zero():
    listing = _listing("plain")
    profile = _profile()

    assert session_prefs.preference_bonus(listing, profile) == 0
