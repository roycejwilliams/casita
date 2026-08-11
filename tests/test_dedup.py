from casita.dedup import dedupe
from casita.models import Listing


def _listing(source, source_id, **kwargs):
    return Listing(source=source, source_id=source_id, url=f"https://{source}.example/{source_id}", **kwargs)


def test_dedupe_one_side_empty_no_conflict_recorded():
    zillow = _listing("zillow", "1", address="123 Main St", price=3000, dog_policy=None)
    craigslist = _listing("craigslist", "1", address="123 Main St", price=3000, dog_policy="dogs_ok")

    [merged] = dedupe([zillow, craigslist])

    assert merged.dog_policy == "dogs_ok"
    assert merged.raw.get("source_conflicts", []) == []


def test_dedupe_prices_differ_within_threshold_conflict_recorded():
    zillow = _listing("zillow", "1", address="123 Main St", price=3000)
    craigslist = _listing("craigslist", "1", address="123 Main St", price=3200)

    [merged] = dedupe([zillow, craigslist])

    assert merged.price == 3000
    assert merged.raw["source_conflicts"] == [
        {"field": "price", "zillow": 3000, "craigslist": 3200}
    ]


def test_dedupe_dog_policy_disagreement_conflict_recorded():
    zillow = _listing("zillow", "1", address="123 Main St", price=3000, dog_policy="no_dogs")
    craigslist = _listing("craigslist", "1", address="123 Main St", price=3000, dog_policy="dogs_ok")

    [merged] = dedupe([zillow, craigslist])

    assert merged.dog_policy == "no_dogs"
    assert merged.raw["source_conflicts"] == [
        {"field": "dog_policy", "zillow": "no_dogs", "craigslist": "dogs_ok"}
    ]


def test_dedupe_parking_disagreement_conflict_recorded():
    zillow = _listing("zillow", "1", address="123 Main St", price=3000, parking="garage")
    craigslist = _listing("craigslist", "1", address="123 Main St", price=3000, parking="street")

    [merged] = dedupe([zillow, craigslist])

    assert merged.parking == "garage"
    assert merged.raw["source_conflicts"] == [
        {"field": "parking", "zillow": "garage", "craigslist": "street"}
    ]


def test_dedupe_matching_values_no_conflict_recorded():
    zillow = _listing("zillow", "1", address="123 Main St", price=3000, laundry="in_unit")
    craigslist = _listing("craigslist", "1", address="123 Main St", price=3000, laundry="in_unit")

    [merged] = dedupe([zillow, craigslist])

    assert merged.raw.get("source_conflicts", []) == []


def test_dedupe_also_on_populates_alongside_conflict_recording():
    zillow = _listing("zillow", "1", address="123 Main St", price=3000)
    craigslist = _listing("craigslist", "1", address="123 Main St", price=3200)

    [merged] = dedupe([zillow, craigslist])

    assert merged.raw["also_on"] == [
        {"source": "craigslist", "url": craigslist.url}
    ]
    assert merged.raw["source_conflicts"] == [
        {"field": "price", "zillow": 3000, "craigslist": 3200}
    ]
