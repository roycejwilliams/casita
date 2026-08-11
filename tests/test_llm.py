import wave
from io import BytesIO

from casita import llm
from casita.llm import EmotionalProfile, LogisticsProfile, PreferenceProfile, VoiceTurn
from casita.models import Listing


def test_extract_preferences_valid_transcript_returns_profile(monkeypatch):
    expected = PreferenceProfile(
        logistics=LogisticsProfile(
            wants_trail_or_beach_access=True,
            needs_in_unit_laundry=True,
            needs_parking=False,
            min_beds=2,
            notes="wants a quiet street",
        ),
        emotional=EmotionalProfile(
            light_preference="abundant",
            view_preference="open",
            condition_preference="well-kept",
            wants_outdoor_space=True,
            desired_feeling="calm retreat, not a party layout",
        ),
    )

    def fake_call_structured(model, system, prompt, schema, **kwargs):
        assert schema is PreferenceProfile
        assert "beach" in prompt.lower()
        return expected

    monkeypatch.setattr(llm, "_call_structured", fake_call_structured)

    result = llm.extract_preferences("We want to be near a beach or trail, love natural light.")

    assert result == expected


def test_extract_preferences_api_failure_returns_none(monkeypatch):
    monkeypatch.setattr(llm, "_call_structured", lambda *a, **k: None)

    assert llm.extract_preferences("anything") is None


class _FakeResponse:
    def __init__(self, text=None, candidates=None):
        self.text = text
        self.candidates = candidates


class _FakeModels:
    def __init__(self, generate_content):
        self.generate_content = generate_content


class _FakeClient:
    def __init__(self, generate_content):
        self.models = _FakeModels(generate_content)


def _voice_turn_profile() -> PreferenceProfile:
    return PreferenceProfile(
        logistics=LogisticsProfile(
            wants_trail_or_beach_access=True,
            needs_in_unit_laundry=False,
            needs_parking=False,
            min_beds=None,
            notes="",
        ),
        emotional=EmotionalProfile(
            light_preference="no_preference",
            view_preference="no_preference",
            condition_preference="no_preference",
            wants_outdoor_space=False,
            desired_feeling="",
        ),
    )


def test_transcribe_and_extract_valid_audio_returns_voice_turn(monkeypatch):
    expected = VoiceTurn(transcript="we want to be near a beach", profile=_voice_turn_profile())
    calls = {}

    def fake_generate_content(*, model, contents, config):
        calls["model"] = model
        calls["config"] = config
        return _FakeResponse(text=expected.model_dump_json())

    monkeypatch.setattr(llm, "_get_client", lambda: _FakeClient(fake_generate_content))

    result = llm.transcribe_and_extract(b"RIFF....WAVEfmt ", prior_transcript="")

    assert result == expected
    assert calls["model"] == llm.VOICE_MODEL
    assert calls["config"].response_schema is VoiceTurn


def test_transcribe_and_extract_api_failure_returns_none(monkeypatch):
    def raising_generate_content(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(llm, "_get_client", lambda: _FakeClient(raising_generate_content))

    assert llm.transcribe_and_extract(b"garbage", prior_transcript="") is None


def test_transcribe_and_extract_no_credentials_returns_none(monkeypatch):
    def fail_get_client():
        raise RuntimeError("Set CASITA_GCP_PROJECT to use Vertex-backed LLM commands.")

    monkeypatch.setattr(llm, "_get_client", fail_get_client)

    assert llm.transcribe_and_extract(b"garbage") is None


def _listing(key: str, **overrides) -> Listing:
    defaults = dict(source="manual", source_id=key, url="", title=f"Listing {key}", price=3000, beds=2, baths=1)
    defaults.update(overrides)
    return Listing(**defaults)


def test_generate_spoken_reply_warm_reply_includes_explanation_phrasing(monkeypatch):
    ranked = [(_listing("a", neighborhood="Inner Richmond"), 10, 5)]
    explanations = ["8 min walk to Baker Beach — matches wanting beach access."]
    captured = {}

    def fake_generate_content(*, model, contents, config):
        captured["contents"] = contents
        return _FakeResponse(text="Sounds like you want to be near the water — Listing a in Inner Richmond is an 8 minute walk to Baker Beach.")

    monkeypatch.setattr(llm, "_get_client", lambda: _FakeClient(fake_generate_content))

    reply = llm.generate_spoken_reply("I want to be near a beach", _voice_turn_profile(), ranked, explanations)

    prompt_text = captured["contents"][0].parts[0].text
    assert "Baker Beach" in prompt_text
    assert "Baker Beach" in reply


def test_generate_spoken_reply_api_failure_returns_plain_fallback(monkeypatch):
    ranked = [(_listing("a", title="Lake Street Flat"), 10, 5)]

    def raising_generate_content(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(llm, "_get_client", lambda: _FakeClient(raising_generate_content))

    reply = llm.generate_spoken_reply("anything", _voice_turn_profile(), ranked, [])

    assert "Lake Street Flat" in reply


def test_generate_spoken_reply_no_listings_returns_plain_fallback(monkeypatch):
    reply = llm.generate_spoken_reply("anything", _voice_turn_profile(), [], [])

    assert reply
    assert "find" in reply.lower()


def test_synthesize_speech_returns_nonempty_playable_wav_bytes(monkeypatch):
    fake_part = type("Part", (), {"inline_data": type("Inline", (), {
        "data": b"\x01\x00\x02\x00\x03\x00",
        "mime_type": "audio/pcm;rate=24000",
    })()})()
    fake_content = type("Content", (), {"parts": [fake_part]})()
    fake_candidate = type("Candidate", (), {"content": fake_content})()

    def fake_generate_content(*, model, contents, config):
        assert model == llm.TTS_MODEL
        assert config.response_modalities == ["AUDIO"]
        return _FakeResponse(candidates=[fake_candidate])

    monkeypatch.setattr(llm, "_get_client", lambda: _FakeClient(fake_generate_content))

    result = llm.synthesize_speech("Here's what I found.")

    assert isinstance(result, bytes) and result
    with wave.open(BytesIO(result), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getframerate() == 24000
        assert wf.getnframes() == 3


def test_synthesize_speech_api_failure_returns_nonempty_fallback_wav(monkeypatch):
    def raising_generate_content(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(llm, "_get_client", lambda: _FakeClient(raising_generate_content))

    result = llm.synthesize_speech("anything")

    assert isinstance(result, bytes) and result
    with wave.open(BytesIO(result), "rb") as wf:
        assert wf.getnframes() > 0
