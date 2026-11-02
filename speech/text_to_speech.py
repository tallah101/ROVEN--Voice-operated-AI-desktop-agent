"""Multilingual voice output. edge-tts neural voices (online) with offline Windows SAPI fallback."""
from __future__ import annotations

import asyncio
import logging
import threading
import time

import numpy as np

from core.reply_format import base_lang

log = logging.getLogger(__name__)


class TextToSpeech:
    def __init__(self, settings) -> None:
        self.settings = settings
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass

    def voice_for(self, lang: str) -> str:
        voices = self.settings.voices
        return voices.get(lang) or voices.get(base_lang(lang)) or voices["en"]

    def speak(self, text: str, lang: str = "en") -> None:
        text = (text or "").strip()
        if not text:
            return
        self._stop.clear()
        if self.settings.tts_engine == "edge":
            try:
                self._speak_edge(text, lang)
                return
            except Exception as exc:
                log.warning("edge-tts failed (%s); using offline SAPI voice", exc)
        self._speak_sapi(text)

    def _speak_edge(self, text: str, lang: str) -> None:
        import edge_tts
        import miniaudio

        voice = self.voice_for(lang)

        async def fetch() -> bytes:
            data = bytearray()
            async for chunk in edge_tts.Communicate(text, voice, rate=self.settings.tts_rate).stream():
                if chunk["type"] == "audio":
                    data.extend(chunk["data"])
            return bytes(data)

        mp3 = asyncio.run(fetch())
        if self._stop.is_set() or not mp3:
            return
        decoded = miniaudio.decode(mp3, output_format=miniaudio.SampleFormat.SIGNED16,
                                   nchannels=1, sample_rate=24000)
        self.play(np.array(decoded.samples, dtype=np.int16), 24000)

    def _speak_sapi(self, text: str) -> None:
        import pyttsx3
        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
        engine.stop()

    def play(self, samples: np.ndarray, sample_rate: int) -> None:
        """Blocking playback that the emergency stop can interrupt."""
        import sounddevice as sd
        sd.play(samples, sample_rate)
        end = time.time() + len(samples) / sample_rate + 0.2
        while time.time() < end:
            if self._stop.is_set():
                sd.stop()
                return
            time.sleep(0.05)
        sd.stop()
