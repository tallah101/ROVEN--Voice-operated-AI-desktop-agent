"""Microphone capture on a background audio thread; 80 ms int16 frames at 16 kHz."""
from __future__ import annotations

import logging
import queue

import numpy as np

log = logging.getLogger(__name__)


class Microphone:
    FRAME = 1280  # 80 ms at 16 kHz — the frame size openWakeWord expects

    def __init__(self, sample_rate: int = 16000, device: int | None = None) -> None:
        self.sample_rate = sample_rate
        self.device = device
        self.q: queue.Queue = queue.Queue(maxsize=250)
        self.level = 0.0
        self.muted = False       # ignore input while ROVEN itself is speaking
        self._stream = None

    @property
    def running(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        import sounddevice as sd
        if self._stream:
            return
        self._stream = sd.InputStream(samplerate=self.sample_rate, channels=1, dtype="int16",
                                      blocksize=self.FRAME, device=self.device, callback=self._callback)
        self._stream.start()
        log.info("Microphone started (device=%s)", self.device)

    def _callback(self, indata, frames, time_info, status) -> None:
        frame = indata[:, 0].copy()
        self.level = min(1.0, float(np.sqrt(np.mean(frame.astype(np.float32) ** 2))) / 5000)
        if self.muted:
            return
        try:
            self.q.put_nowait(frame)
        except queue.Full:
            try:
                self.q.get_nowait()
                self.q.put_nowait(frame)
            except queue.Empty:
                pass

    def read(self, timeout: float = 0.3) -> np.ndarray | None:
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self) -> None:
        while True:
            try:
                self.q.get_nowait()
            except queue.Empty:
                return

    def stop(self) -> None:
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None
                self.level = 0.0
                self.drain()
                log.info("Microphone stopped")

    @staticmethod
    def list_devices() -> list[tuple[int, str]]:
        import sounddevice as sd
        return [(i, d["name"]) for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]
