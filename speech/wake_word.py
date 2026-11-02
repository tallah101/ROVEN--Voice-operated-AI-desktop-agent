"""Local wake-word detection. Audio never leaves the PC for wake detection.

Engines (best first):
  openwakeword    - custom 'roven' ONNX model (train once; see README). Lowest CPU, best accuracy.
  porcupine       - custom 'roven' .ppn from Picovoice Console + access key.
  whisper_keyword - zero-setup fallback: tiny Whisper on short speech bursts + fuzzy match. More CPU.

process(frame) returns None (no wake), "" (wake) or "<rest of sentence>" when the user said
"Roven, open Chrome" in one breath (whisper_keyword only).
"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np

from speech.audio_processing import EnergyVAD

log = logging.getLogger(__name__)


class WakeDetector:
    name = "base"

    def process(self, frame: np.ndarray) -> str | None:
        raise NotImplementedError

    def reset(self) -> None:
        pass


class OpenWakeWordDetector(WakeDetector):
    name = "openwakeword"

    def __init__(self, model_path: str, threshold: float) -> None:
        if not model_path or not Path(model_path).exists():
            raise FileNotFoundError("No custom 'roven' openWakeWord model configured (wake_model_path).")
        import openwakeword
        from openwakeword.model import Model
        try:
            openwakeword.utils.download_models()   # shared feature models (one-time download)
        except Exception:
            log.warning("Could not download openWakeWord feature models; assuming they exist")
        framework = "onnx" if model_path.lower().endswith(".onnx") else "tflite"
        self.model = Model(wakeword_models=[model_path], inference_framework=framework)
        self.threshold = threshold

    def process(self, frame):
        scores = self.model.predict(frame)
        if max(scores.values(), default=0.0) >= self.threshold:
            self.model.reset()
            return ""
        return None

    def reset(self):
        self.model.reset()


class PorcupineDetector(WakeDetector):
    name = "porcupine"

    def __init__(self, keyword_path: str, sensitivity: float, access_key: str) -> None:
        import pvporcupine
        if not access_key:
            raise ValueError("Porcupine needs an access key (store it with scripts/setup_keys.py).")
        self.p = pvporcupine.create(access_key=access_key, keyword_paths=[keyword_path], sensitivities=[sensitivity])
        self.buf = np.zeros(0, dtype=np.int16)

    def process(self, frame):
        self.buf = np.concatenate([self.buf, frame])
        n = self.p.frame_length
        while len(self.buf) >= n:
            chunk, self.buf = self.buf[:n], self.buf[n:]
            if self.p.process(chunk) >= 0:
                self.buf = np.zeros(0, dtype=np.int16)
                return ""
        return None

    def reset(self):
        self.buf = np.zeros(0, dtype=np.int16)


LEAD_INS = {"hey", "hi", "ok", "okay", "oye", "oy", "acha", "achha", "haan", "han", "so", "um", "uh", "ارے", "اوئے", "अरे"}


def match_wake_phrase(text: str, phrases: list[str], threshold: float = 0.75) -> str | None:
    """If the utterance starts with the wake word (optionally after 'hey', 'ok', 'oye'…), return the text after it.
    Requiring it at the start avoids waking when the word is merely mentioned ('I told Robin…')."""
    tokens = list(re.finditer(r"\w+", text, re.UNICODE))
    targets = [p.lower().replace(" ", "") for p in phrases]
    start = 1 if tokens and tokens[0].group().lower() in LEAD_INS else 0
    for i, tok in list(enumerate(tokens))[start:start + 1]:
        single = tok.group().lower()
        pair = single + (tokens[i + 1].group().lower() if i + 1 < len(tokens) else "")
        for target in targets:
            if SequenceMatcher(None, single, target).ratio() >= threshold:
                end = tok.end()
            elif i + 1 < len(tokens) and SequenceMatcher(None, pair, target).ratio() >= threshold:
                end = tokens[i + 1].end()
            else:
                continue
            return text[end:].strip(" ,.!?;:،۔-")
    return None


class WhisperKeywordDetector(WakeDetector):
    name = "whisper_keyword"

    def __init__(self, phrases: list[str], model_size: str = "tiny", sample_rate: int = 16000) -> None:
        self.phrases = phrases
        self.model_size = model_size
        self.sample_rate = sample_rate
        self.vad = EnergyVAD()
        self._model = None
        self._buf: list[np.ndarray] = []
        self._silent = 0.0
        self.last_audio: np.ndarray | None = None      # audio of the last wake, for accurate re-transcription

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            from speech.speech_to_text import resolve_model
            self._model = WhisperModel(resolve_model(self.model_size), device="cpu", compute_type="int8")
        return self._model

    def process(self, frame):
        dur = len(frame) / self.sample_rate
        speech = self.vad.is_speech(frame)
        if not self._buf:
            if speech:
                self._buf = [frame]
                self._silent = 0.0
            return None
        self._buf.append(frame)
        self._silent = 0.0 if speech else self._silent + dur
        total = len(self._buf) * dur
        if self._silent < 0.6 and total < 6.0:
            return None
        audio = np.concatenate(self._buf)
        self._buf = []
        if total < 0.35:
            return None
        # The prompt tells Whisper the word "Roven" exists, so it spells it that way instead of "Rowan"/"Robin".
        segments, _ = self._load().transcribe(audio.astype(np.float32) / 32768.0, beam_size=1,
                                              condition_on_previous_text=False, without_timestamps=True,
                                              initial_prompt="Roven.")
        text = " ".join(s.text for s in segments).strip()
        if not text:
            return None
        hit = match_wake_phrase(text, self.phrases)
        if hit is not None:
            self.last_audio = audio
            log.info("Wake word detected in: %r", text)
        elif match_wake_phrase(text, self.phrases, threshold=0.5) is not None:
            log.info("Almost woke (heard %r) — if this was you saying Roven, add that spelling to wake_phrases", text)
        return hit

    def reset(self):
        self._buf = []


def create_detector(settings) -> WakeDetector:
    engine = settings.wake_engine
    try:
        if engine == "openwakeword":
            return OpenWakeWordDetector(settings.wake_model_path, settings.wake_threshold)
        if engine == "porcupine":
            from security.credentials import get_secret
            return PorcupineDetector(settings.wake_model_path, settings.porcupine_sensitivity,
                                     get_secret("porcupine_access_key") or "")
    except Exception as exc:
        log.warning("Wake engine '%s' unavailable (%s); falling back to whisper_keyword", engine, exc)
    return WhisperKeywordDetector(settings.wake_phrases, settings.keyword_model, settings.sample_rate)
