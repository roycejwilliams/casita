import shutil

import casita
from casita import chat_api, llm
from casita.llm import EmotionalProfile, LogisticsProfile, PreferenceProfile


def _set_demo_env(monkeypatch, tmp_path):
    db_path = tmp_path / "demo.sqlite"
    shutil.copy2(casita.DEMO_FIXTURE, db_path)
    monkeypatch.setenv("CASITA_DB_PATH", str(db_path))
    monkeypatch.setenv("CASITA_ROUTE_CACHE_DB", str(db_path))
    monkeypatch.setenv("CASITA_ROUTES_OFFLINE", "1")


def _fake_profile() -> PreferenceProfile:
    return PreferenceProfile(
        logistics=LogisticsProfile(
            wants_trail_or_beach_access=True,
            needs_in_unit_laundry=False,
            needs_parking=True,
            min_beds=None,
            notes="",
        ),
        emotional=EmotionalProfile(
            light_preference="abundant",
            view_preference="open",
            condition_preference="well-kept",
            wants_outdoor_space=True,
            desired_feeling="",
        ),
    )


def teardown_function(_fn):
    chat_api.reset_session()


def test_handle_message_success_returns_expected_dict_shape(monkeypatch, tmp_path):
    _set_demo_env(monkeypatch, tmp_path)
    chat_api.reset_session()
    monkeypatch.setattr(llm, "extract_preferences", lambda transcript: _fake_profile())
    monkeypatch.setattr(llm, "generate_spoken_reply", lambda *a, **k: "here's what I found")

    result = chat_api.handle_message("we need parking and a sunny place near a trail")

    assert result["reply"] == "here's what I found"
    assert "logistics" in result["profile"]
    assert "emotional" in result["profile"]
    assert isinstance(result["ranked"], list)
    assert len(result["ranked"]) <= 10
    if result["ranked"]:
        entry = result["ranked"][0]
        for field in ["key", "title", "hood", "price", "image_url", "dog_policy", "base", "bonus", "total", "explanation"]:
            assert field in entry
        assert entry["total"] == entry["base"] + entry["bonus"]


def test_handle_message_two_calls_second_transcript_contains_both_messages(monkeypatch, tmp_path):
    _set_demo_env(monkeypatch, tmp_path)
    chat_api.reset_session()
    calls: list[str] = []

    def fake_extract(transcript):
        calls.append(transcript)
        return _fake_profile()

    monkeypatch.setattr(llm, "extract_preferences", fake_extract)
    monkeypatch.setattr(llm, "generate_spoken_reply", lambda *a, **k: "ok")

    chat_api.handle_message("first message about parking")
    chat_api.handle_message("second message about laundry")

    assert len(calls) == 2
    assert "parking" in calls[1]
    assert "laundry" in calls[1]


def test_handle_message_extract_failure_returns_error_without_crashing(monkeypatch, tmp_path):
    _set_demo_env(monkeypatch, tmp_path)
    chat_api.reset_session()
    monkeypatch.setattr(llm, "extract_preferences", lambda transcript: None)

    result = chat_api.handle_message("anything")

    assert "error" in result
    assert "couldn't extract a preference profile" in result["error"]


def test_reset_session_clears_prior_transcript(monkeypatch, tmp_path):
    _set_demo_env(monkeypatch, tmp_path)
    chat_api.reset_session()
    calls: list[str] = []

    def fake_extract(transcript):
        calls.append(transcript)
        return _fake_profile()

    monkeypatch.setattr(llm, "extract_preferences", fake_extract)
    monkeypatch.setattr(llm, "generate_spoken_reply", lambda *a, **k: "ok")

    chat_api.handle_message("first message about parking")
    chat_api.reset_session()
    chat_api.handle_message("second message about laundry")

    assert "parking" not in calls[1]
    assert "laundry" in calls[1]
