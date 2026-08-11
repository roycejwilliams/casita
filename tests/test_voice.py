import io
import wave

import numpy as np

from casita import voice


class _FakeInputStream:
    """Stands in for sounddevice.InputStream: feeds one fake frame batch to
    the callback on enter, like real audio would arrive on a background
    thread while the caller blocks on the second input().
    """

    def __init__(self, samplerate, channels, dtype, callback):
        self.callback = callback
        self._fed = np.array([[100], [200], [300], [-400]], dtype=np.int16)

    def __enter__(self):
        self.callback(self._fed, len(self._fed), None, None)
        return self

    def __exit__(self, *exc):
        return False


def test_record_turn_produces_valid_mono_16khz_wav(monkeypatch):
    prompts: list[str] = []
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt))
    monkeypatch.setattr(voice.sd, "InputStream", _FakeInputStream)

    result = voice.record_turn()

    assert isinstance(result, bytes) and result
    with wave.open(io.BytesIO(result), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == voice.SAMPLE_RATE
        raw = wf.readframes(wf.getnframes())
    samples = np.frombuffer(raw, dtype=np.int16)
    assert samples.tolist() == [100, 200, 300, -400]
    assert len(prompts) == 2  # start prompt, stop prompt


def test_record_turn_no_audio_captured_still_returns_valid_wav(monkeypatch):
    class _EmptyStream(_FakeInputStream):
        def __enter__(self):
            return self  # never invokes the callback

    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    monkeypatch.setattr(voice.sd, "InputStream", _EmptyStream)

    result = voice.record_turn()

    with wave.open(io.BytesIO(result), "rb") as wf:
        assert wf.getnframes() == 0


def test_play_audio_decodes_wav_and_calls_sounddevice_play_with_right_rate(monkeypatch):
    samples = np.array([1, 2, 3, 4, 5], dtype=np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(samples.tobytes())
    wav_bytes = buf.getvalue()

    calls = {}

    def fake_play(data, samplerate=None):
        calls["data"] = data
        calls["samplerate"] = samplerate

    monkeypatch.setattr(voice.sd, "play", fake_play)
    monkeypatch.setattr(voice.sd, "wait", lambda: calls.setdefault("waited", True))

    voice.play_audio(wav_bytes)

    assert calls["samplerate"] == 22050
    assert calls["data"].tolist() == samples.tolist()
    assert calls["waited"] is True
