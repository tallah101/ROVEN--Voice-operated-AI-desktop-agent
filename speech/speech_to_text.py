"""Multilingual speech recognition with faster-whisper and automatic language detection."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)


def resolve_model(size: str) -> str:
    """Use the speech model bundled by the installer if present (works offline); else download by name."""
    from core.paths import app_root
    bundled = app_root() / "models" / f"faster-whisper-{size}"
    return str(bundled) if (bundled / "model.bin").exists() else size


@dataclass
class Transcript:
    text: str
    language: str
    probability: float


class SpeechToText:
    def __init__(self, model_size: str, device: str, compute_type: str, vocabulary: list[str]) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.vocabulary = vocabulary
        self._model = None
        self._lock = threading.Lock()

    def load(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel
                source = resolve_model(self.model_size)
                log.info("Loading Whisper '%s' on %s", source, self.device)
                self._model = WhisperModel(source, device=self.device, compute_type=self.compute_type)
        return self._model

    def transcribe(self, audio: np.ndarray) -> Transcript:
        model = self.load()
        # Names only: a long English prompt would bias Whisper toward English output.
        prompt = ", ".join(self.vocabulary) + "."
        segments, info = model.transcribe(
            audio.astype(np.float32) / 32768.0,
            language=None,                 # auto-detect every utterance
            beam_size=5,
            vad_filter=True,
            initial_prompt=prompt,
            condition_on_previous_text=False,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        log.info("STT [%s %.2f]: %s", info.language, info.language_probability, text)
        return Transcript(text, info.language, info.language_probability)


GEMINI_STT_PROMPT = """Transcribe this short voice command spoken to a Windows desktop assistant named Roven.
Return only JSON: {{"text": "<exactly what was said>", "language": "<ISO 639-1 code of the main spoken language>"}}.
Rules: write Urdu or Hindi speech in Roman Urdu (Latin letters) unless the speaker clearly spoke English;
keep English words, app names, people's names and technical terms exactly as spoken; do not translate,
answer or add anything; if there is no speech, return an empty text. Names the user often says: {names}."""


def wav_bytes(audio: np.ndarray, sample_rate: int = 16000) -> bytes:
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(audio.astype(np.int16).tobytes())
    return buf.getvalue()


def parse_transcript_json(text: str) -> tuple[str, str]:
    import json
    import re
    raw = text.strip()
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        try:
            data = json.loads(m.group(0))
            return str(data.get("text", "")).strip(), str(data.get("language", "") or "en").strip().lower()
        except ValueError:
            pass
    return raw.strip('"').strip(), "en"


class GeminiSpeechToText:
    """Sends the recorded command to Gemini, which understands Urdu, Roman Urdu and mixed speech far better than a
    small offline model. Falls back to local Whisper if Gemini can't be reached."""

    def __init__(self, gemini_client, fallback: SpeechToText, vocabulary: list[str], sample_rate: int = 16000) -> None:
        self.gemini = gemini_client
        self.fallback = fallback
        self.vocabulary = vocabulary
        self.sample_rate = sample_rate

    def load(self):
        return None            # nothing to load; Whisper loads only if it's ever needed as a fallback

    def transcribe(self, audio: np.ndarray) -> Transcript:
        try:
            started = __import__("time").time()
            out = self.gemini.transcribe_audio(wav_bytes(audio, self.sample_rate),
                                               GEMINI_STT_PROMPT.format(names=", ".join(self.vocabulary)))
            text, lang = parse_transcript_json(out)
            log.info("STT (Gemini, %.1fs) [%s]: %s", __import__("time").time() - started, lang, text)
            return Transcript(text, lang, 1.0)
        except Exception as exc:
            log.warning("Gemini transcription failed (%s); using offline Whisper", exc)
            return self.fallback.transcribe(audio)
