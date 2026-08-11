"""Local audio hardware I/O for `casita demo --voice` — capture and playback
only. No Gemini calls live here; see `llm.py`'s `transcribe_and_extract`,
`generate_spoken_reply`, and `synthesize_speech` for the model side.

Requires PortAudio at the OS level (`brew install portaudio` on macOS) —
that's what `sounddevice` binds to. This is only a dependency of the
`--voice` path; the credentials-free base demo and `--intake` never import
this module.
"""
import io
import wave

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
_CHANNELS = 1
_DTYPE = "int16"


def record_turn() -> bytes:
    """Push-to-talk capture: Enter to start, Enter to stop. Returns 16-bit
    PCM mono WAV bytes at `SAMPLE_RATE`.
    """
    input("Press Enter to start talking, Enter again to stop.")

    frames: list[np.ndarray] = []

    def _callback(indata, frame_count, time_info, status):
        frames.append(indata.copy())

    with sd.InputStream(
        samplerate=SAMPLE_RATE, channels=_CHANNELS, dtype=_DTYPE, callback=_callback,
    ):
        input("Recording... press Enter to stop.")

    samples = np.concatenate(frames, axis=0) if frames else np.zeros((0, _CHANNELS), dtype=_DTYPE)
    return _encode_wav(samples)


def play_audio(audio_bytes: bytes) -> None:
    """Decode WAV bytes and play them back synchronously."""
    samples, sample_rate = _decode_wav(audio_bytes)
    sd.play(samples, samplerate=sample_rate)
    sd.wait()


def _encode_wav(samples: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(_CHANNELS)
        wf.setsampwidth(np.dtype(_DTYPE).itemsize)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(samples.tobytes())
    return buf.getvalue()


def _decode_wav(audio_bytes: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
        sample_rate = wf.getframerate()
        channels = wf.getnchannels()
        raw = wf.readframes(wf.getnframes())
    samples = np.frombuffer(raw, dtype=_DTYPE)
    if channels > 1:
        samples = samples.reshape(-1, channels)
    return samples, sample_rate
