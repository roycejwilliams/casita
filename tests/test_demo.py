import io
import json
import shutil
import importlib.util
import re
import wave
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import casita
from casita import chat_api, html, listing_page, llm
from casita.llm import EmotionalProfile, LogisticsProfile, PreferenceProfile, VoiceTurn
from casita.models import Listing


PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def test_demo_fixture_renders_offline(tmp_path, monkeypatch):
    fixture = casita.DEMO_FIXTURE
    db_path = tmp_path / "demo.sqlite"
    output_dir = tmp_path / "site"
    shutil.copy2(fixture, db_path)

    monkeypatch.setenv("CASITA_DB_PATH", str(db_path))
    monkeypatch.setenv("CASITA_ROUTE_CACHE_DB", str(db_path))
    monkeypatch.setenv("CASITA_ROUTES_OFFLINE", "1")
    monkeypatch.setenv("CASITA_SITE_URL", "http://127.0.0.1:8765")

    result = casita._render_site("index.html", output_dir)

    assert result["listings"] > 100
    assert result["details"] == result["listings"]
    assert result["og_images"] == result["details"] + 1
    assert result["out_html"].exists()
    assert (output_dir / "og" / "index.png").read_bytes().startswith(PNG_HEADER)
    listing_pages = list((output_dir / "listing").glob("*.html"))
    assert len(listing_pages) == result["details"]
    first_listing = listing_pages[0]
    assert f"/og/listing/{first_listing.stem}.png" in first_listing.read_text()
    assert (output_dir / "og" / "listing" / f"{first_listing.stem}.png").read_bytes().startswith(PNG_HEADER)
    assert "/og/index.png" in result["out_html"].read_text()
    assert (output_dir / "assets" / "favicon.svg").exists()

    local_refs = []
    for page in [result["out_html"], *listing_pages]:
        for match in re.finditer(r"""(?:src|href)=["']([^"']+)["']""", page.read_text()):
            url = match.group(1)
            if url.startswith("/") and not url.startswith("//"):
                local_refs.append((page, url))
    missing = [
        f"{page.relative_to(output_dir)} -> {url}"
        for page, url in local_refs
        if not (output_dir / url.lstrip("/")).exists()
        and not (output_dir / f"{url.lstrip('/')}.html").exists()
    ]
    assert missing == []

    with casita._serve_rendered_site(output_dir) as base_url:
        with urlopen(f"{base_url}/", timeout=5) as response:
            assert response.status == 200
        with urlopen(f"{base_url}/listing/{first_listing.stem}", timeout=5) as response:
            assert response.status == 200
        with urlopen(f"{base_url}/og/listing/{first_listing.stem}.png", timeout=5) as response:
            assert response.status == 200
            assert response.headers.get_content_type() == "image/png"


def test_package_fixture_matches_repo_fixture():
    assert casita.DEMO_FIXTURE.read_bytes() == (
        casita.ROOT / "fixtures" / "demo.sqlite"
    ).read_bytes()


def test_default_scrub_redacts_contact_info_without_matching_coordinates():
    phone = "415" + "-555" + "-1212"
    text = listing_page._scrub(f"Call {phone} or leasing@example.com")
    assert text == "Call [redacted] or [redacted]"
    assert listing_page._scrub("37.956-122.3933") == "37.956-122.3933"


def test_index_open_graph_urls_are_escaped(monkeypatch):
    monkeypatch.setenv("CASITA_SITE_URL", 'https://example.test/"bad')
    rendered = html.render(
        [Listing(
            source="manual",
            source_id="1",
            url="",
            title="Demo listing",
            address="1 Demo St",
            neighborhood="demo",
            price=1000,
            beds=1,
            baths=1,
            dog_policy="dogs_ok",
            llm_severity="ok",
        )],
        run={"started_at": "2026-01-01T00:00:00", "finished_at": "2026-01-01T00:00:00"},
    )

    assert 'content="https://example.test/&quot;bad/og/index.png"' in rendered


def test_demo_clean_url_path_resolves_listing_html(tmp_path):
    listing = tmp_path / "listing" / "sample-listing.html"
    listing.parent.mkdir()
    listing.write_text("<h1>Sample listing</h1>")

    resolved = casita._demo_clean_url_path(
        "/listing/sample-listing",
        tmp_path / "listing" / "sample-listing",
    )

    assert resolved == str(listing)


def test_rendered_site_server_serves_clean_urls_and_assets(tmp_path):
    (tmp_path / "index.html").write_text("home")
    listing = tmp_path / "listing" / "sample-listing.html"
    listing.parent.mkdir()
    listing.write_text("detail")
    image = tmp_path / "og" / "index.png"
    image.parent.mkdir()
    image.write_bytes(PNG_HEADER + b"demo")

    with casita._serve_rendered_site(tmp_path) as base_url:
        with urlopen(f"{base_url}/", timeout=5) as response:
            assert response.status == 200
            assert response.read() == b"home"
        with urlopen(f"{base_url}/listing/sample-listing", timeout=5) as response:
            assert response.status == 200
            assert response.read() == b"detail"
        with urlopen(f"{base_url}/og/index.png", timeout=5) as response:
            assert response.status == 200
            assert response.headers.get_content_type() == "image/png"
            assert response.read().startswith(PNG_HEADER)


def _fake_chat_profile() -> PreferenceProfile:
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


def _post_json(base_url, path, payload_bytes):
    req = Request(f"{base_url}{path}", data=payload_bytes, method="POST",
                   headers={"Content-Type": "application/json"})
    return urlopen(req, timeout=5)


def test_post_api_chat_returns_json_reply_and_ranked_listings(monkeypatch, tmp_path):
    _set_intake_demo_env(monkeypatch, tmp_path)
    chat_api.reset_session()
    monkeypatch.setattr(llm, "extract_preferences", lambda transcript: _fake_chat_profile())
    monkeypatch.setattr(llm, "generate_spoken_reply", lambda *a, **k: "here's what I found")

    output_dir = tmp_path / "site"
    output_dir.mkdir()
    (output_dir / "index.html").write_text("home")

    with casita._serve_rendered_site(output_dir) as base_url:
        with _post_json(base_url, "/api/chat", json.dumps({"message": "near a trail, need parking"}).encode()) as response:
            assert response.status == 200
            assert response.headers.get_content_type() == "application/json"
            data = json.loads(response.read())
            assert data["reply"] == "here's what I found"
            assert "logistics" in data["profile"]
            assert isinstance(data["ranked"], list)


def test_post_api_chat_reset_clears_transcript(monkeypatch, tmp_path):
    _set_intake_demo_env(monkeypatch, tmp_path)
    chat_api.reset_session()
    calls: list[str] = []

    def fake_extract(transcript):
        calls.append(transcript)
        return _fake_chat_profile()

    monkeypatch.setattr(llm, "extract_preferences", fake_extract)
    monkeypatch.setattr(llm, "generate_spoken_reply", lambda *a, **k: "ok")

    output_dir = tmp_path / "site"
    output_dir.mkdir()
    (output_dir / "index.html").write_text("home")

    with casita._serve_rendered_site(output_dir) as base_url:
        with _post_json(base_url, "/api/chat", json.dumps({"message": "first turn about parking"}).encode()):
            pass
        with _post_json(base_url, "/api/chat/reset", b"{}") as response:
            assert response.status == 200
            assert json.loads(response.read()) == {"ok": True}
        with _post_json(base_url, "/api/chat", json.dumps({"message": "second turn about laundry"}).encode()):
            pass

    assert "parking" not in calls[-1]
    assert "laundry" in calls[-1]


def test_post_api_chat_malformed_json_body_returns_clean_4xx(tmp_path):
    output_dir = tmp_path / "site"
    output_dir.mkdir()
    (output_dir / "index.html").write_text("home")

    with casita._serve_rendered_site(output_dir) as base_url:
        try:
            _post_json(base_url, "/api/chat", b"{not valid json")
            raise AssertionError("expected an HTTPError for malformed JSON")
        except HTTPError as e:
            assert 400 <= e.code < 500
            body = json.loads(e.read())
            assert "error" in body


def test_post_api_chat_without_credentials_returns_graceful_json_error(monkeypatch, tmp_path):
    _set_intake_demo_env(monkeypatch, tmp_path)
    chat_api.reset_session()
    monkeypatch.setattr(llm, "extract_preferences", lambda transcript: None)

    output_dir = tmp_path / "site"
    output_dir.mkdir()
    (output_dir / "index.html").write_text("home")

    with casita._serve_rendered_site(output_dir) as base_url:
        with _post_json(base_url, "/api/chat", json.dumps({"message": "anything"}).encode()) as response:
            assert response.status == 200
            data = json.loads(response.read())
            assert "error" in data


def _set_intake_demo_env(monkeypatch, tmp_path):
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


def test_run_intake_two_rounds_reextracts_on_full_cumulative_transcript(monkeypatch, tmp_path):
    _set_intake_demo_env(monkeypatch, tmp_path)

    # turn 1: "near a beach or trail" then blank ends the turn's collection.
    # turn 2: "and needs parking too" then "done" ends the turn's collection.
    # turn 3: blank immediately -> exits the outer loop.
    scripted_inputs = iter(
        ["near a beach or trail", "", "and needs parking too", "done", ""]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(scripted_inputs))

    calls: list[str] = []

    def fake_extract(transcript):
        calls.append(transcript)
        return _fake_profile()

    monkeypatch.setattr(llm, "extract_preferences", fake_extract)

    casita._run_intake()

    assert len(calls) >= 2
    assert "beach" in calls[0]
    assert "beach" in calls[1] and "parking" in calls[1]


def test_run_intake_blank_first_turn_exits_without_extracting(monkeypatch, tmp_path, capsys):
    _set_intake_demo_env(monkeypatch, tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt="": "")

    def fail_extract(transcript):
        raise AssertionError("extract_preferences should not be called")

    monkeypatch.setattr(llm, "extract_preferences", fail_extract)

    casita._run_intake()

    assert "no preferences entered" in capsys.readouterr().out


def test_run_intake_extract_preferences_none_prints_error_and_stops(monkeypatch, tmp_path, capsys):
    _set_intake_demo_env(monkeypatch, tmp_path)
    scripted_inputs = iter(["something", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(scripted_inputs))
    monkeypatch.setattr(llm, "extract_preferences", lambda transcript: None)

    casita._run_intake()

    assert "couldn't extract a preference profile" in capsys.readouterr().out


def _wav_bytes(n_frames: int) -> bytes:
    """16-bit PCM mono WAV with `n_frames` zero samples — 0 frames is what
    `voice.record_turn()` returns when the person presses Enter twice
    without speaking; a positive count is any non-silent turn.
    """
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * n_frames)
    return buf.getvalue()


def _fake_reply_recorder(calls: list):
    def fake_reply(transcript, profile, ranked, explanations, *, wrap_up=False):
        calls.append((transcript, wrap_up))
        return "spoken reply"
    return fake_reply


def test_run_voice_two_turns_prior_transcript_contains_first_turn(monkeypatch, tmp_path):
    _set_intake_demo_env(monkeypatch, tmp_path)
    from casita import voice

    # turn 1: real content. turn 2: real content (prior_transcript should
    # carry turn 1's transcript). turn 3: silence ends the loop.
    recordings = iter([_wav_bytes(100), _wav_bytes(100), _wav_bytes(0)])
    monkeypatch.setattr(voice, "record_turn", lambda: next(recordings))
    monkeypatch.setattr(voice, "play_audio", lambda audio: None)

    prior_transcripts: list[str] = []

    def fake_transcribe(audio, *, prior_transcript=""):
        prior_transcripts.append(prior_transcript)
        text = "near a beach or trail" if len(prior_transcripts) == 1 else "and needs parking too"
        return VoiceTurn(transcript=text, profile=_fake_profile(), ready_to_wrap_up=False)

    monkeypatch.setattr(llm, "transcribe_and_extract", fake_transcribe)
    monkeypatch.setattr(llm, "generate_spoken_reply", lambda *a, **k: "ok")
    monkeypatch.setattr(llm, "synthesize_speech", lambda text: b"")

    casita._run_voice()

    assert len(prior_transcripts) == 2
    assert prior_transcripts[0] == ""
    assert "near a beach or trail" in prior_transcripts[1]


def test_run_voice_silent_first_turn_exits_without_transcribing(monkeypatch, tmp_path, capsys):
    _set_intake_demo_env(monkeypatch, tmp_path)
    from casita import voice

    monkeypatch.setattr(voice, "record_turn", lambda: _wav_bytes(0))

    def fail_transcribe(*a, **k):
        raise AssertionError("transcribe_and_extract should not be called")

    monkeypatch.setattr(llm, "transcribe_and_extract", fail_transcribe)

    casita._run_voice()

    assert "no preferences entered" in capsys.readouterr().out


def test_run_voice_silent_turn_after_content_stops_loop_cleanly(monkeypatch, tmp_path):
    _set_intake_demo_env(monkeypatch, tmp_path)
    from casita import voice

    recordings = iter([_wav_bytes(100), _wav_bytes(0)])
    monkeypatch.setattr(voice, "record_turn", lambda: next(recordings))
    played: list[bytes] = []
    monkeypatch.setattr(voice, "play_audio", lambda audio: played.append(audio))
    monkeypatch.setattr(
        llm, "transcribe_and_extract",
        lambda audio, *, prior_transcript="": VoiceTurn(
            transcript="near a beach", profile=_fake_profile(), ready_to_wrap_up=False
        ),
    )
    reply_calls: list = []
    monkeypatch.setattr(llm, "generate_spoken_reply", _fake_reply_recorder(reply_calls))
    monkeypatch.setattr(llm, "synthesize_speech", lambda text: b"audio")

    casita._run_voice()

    # turn 1 continues the conversation (wrap_up=False); the trailing
    # silence then produces a wrap-up reply (wrap_up=True) before stopping.
    assert [wrap_up for _transcript, wrap_up in reply_calls] == [False, True]
    assert len(played) == 2


def test_run_voice_spoken_done_with_content_processes_then_stops(monkeypatch, tmp_path):
    _set_intake_demo_env(monkeypatch, tmp_path)
    from casita import voice

    monkeypatch.setattr(voice, "record_turn", lambda: _wav_bytes(100))
    played: list[bytes] = []
    monkeypatch.setattr(voice, "play_audio", lambda audio: played.append(audio))
    monkeypatch.setattr(
        llm, "transcribe_and_extract",
        lambda audio, *, prior_transcript="": VoiceTurn(
            transcript="I need parking too, that's all", profile=_fake_profile(), ready_to_wrap_up=False
        ),
    )
    reply_calls: list = []
    monkeypatch.setattr(llm, "generate_spoken_reply", _fake_reply_recorder(reply_calls))
    monkeypatch.setattr(llm, "synthesize_speech", lambda text: b"audio")

    casita._run_voice()

    # processed once — record_turn is only ever called once because the
    # loop stops right after — with the real content and wrap_up=True,
    # since the person said goodbye in the same breath.
    assert len(reply_calls) == 1
    transcript, wrap_up = reply_calls[0]
    assert "parking" in transcript
    assert wrap_up is True


def test_run_voice_transcribe_and_extract_none_prints_error_and_returns(monkeypatch, tmp_path, capsys):
    _set_intake_demo_env(monkeypatch, tmp_path)
    from casita import voice

    monkeypatch.setattr(voice, "record_turn", lambda: _wav_bytes(100))
    monkeypatch.setattr(llm, "transcribe_and_extract", lambda audio, *, prior_transcript="": None)

    casita._run_voice()

    assert "couldn't transcribe/extract" in capsys.readouterr().out


def test_run_voice_ready_to_wrap_up_stops_after_processing(monkeypatch, tmp_path):
    _set_intake_demo_env(monkeypatch, tmp_path)
    from casita import voice

    monkeypatch.setattr(voice, "record_turn", lambda: _wav_bytes(100))
    played: list[bytes] = []
    monkeypatch.setattr(voice, "play_audio", lambda audio: played.append(audio))
    monkeypatch.setattr(
        llm, "transcribe_and_extract",
        lambda audio, *, prior_transcript="": VoiceTurn(
            transcript="two beds, parking, near a trail", profile=_fake_profile(), ready_to_wrap_up=True
        ),
    )
    reply_calls: list = []
    monkeypatch.setattr(llm, "generate_spoken_reply", _fake_reply_recorder(reply_calls))
    monkeypatch.setattr(llm, "synthesize_speech", lambda text: b"audio")

    casita._run_voice()

    assert [wrap_up for _transcript, wrap_up in reply_calls] == [True]


def test_run_voice_time_cap_speaks_wrapup_without_recording_again(monkeypatch, tmp_path):
    _set_intake_demo_env(monkeypatch, tmp_path)
    from casita import voice

    # monotonic() is called once for `start`, then once per loop-top check.
    # Turn 1 fits comfortably inside the cap; by the second check the cap
    # has elapsed, so a second record_turn() must never happen.
    clock = iter([0.0, 0.0, 1000.0])
    monkeypatch.setattr(casita.time, "monotonic", lambda: next(clock, 1000.0))

    record_calls: list = []

    def fake_record():
        record_calls.append(1)
        return _wav_bytes(100)

    monkeypatch.setattr(voice, "record_turn", fake_record)
    monkeypatch.setattr(voice, "play_audio", lambda audio: None)
    monkeypatch.setattr(
        llm, "transcribe_and_extract",
        lambda audio, *, prior_transcript="": VoiceTurn(
            transcript="near a trail", profile=_fake_profile(), ready_to_wrap_up=False
        ),
    )
    reply_calls: list = []
    monkeypatch.setattr(llm, "generate_spoken_reply", _fake_reply_recorder(reply_calls))
    monkeypatch.setattr(llm, "synthesize_speech", lambda text: b"audio")

    casita._run_voice()

    assert record_calls == [1]
    assert [wrap_up for _transcript, wrap_up in reply_calls] == [False, True]


def test_public_validator_passes():
    path = casita.ROOT / "scripts" / "validate_public.py"
    spec = importlib.util.spec_from_file_location("validate_public", path)
    assert spec and spec.loader
    validate_public = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validate_public)

    validate_public.main()
