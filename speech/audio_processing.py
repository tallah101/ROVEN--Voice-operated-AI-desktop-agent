"""Energy-based voice activity detection and utterance recording."""
from __future__ import annotations

import threading
from collections import deque
from typing import Callable

import numpy as np


def rms(frame: np.ndarray) -> float:
    return float(np.sqrt(np.mean(frame.astype(np.float32) ** 2))) if len(frame) else 0.0


class EnergyVAD:
    """Adaptive threshold: tracks the room's noise floor and flags frames well above it."""

    def __init__(self, min_threshold: float = 350.0, ratio: float = 3.0) -> None:
        self.min_threshold = min_threshold
        self.ratio = ratio
        self.noise = 200.0

    def is_speech(self, frame: np.ndarray) -> bool:
        level = rms(frame)
        speech = level > max(self.min_threshold, self.noise * self.ratio)
        if not speech:
            self.noise = 0.95 * self.noise + 0.05 * level
        return speech


def record_utterance(read_frame: Callable[[float], np.ndarray | None], vad: EnergyVAD, sample_rate: int,
                     start_timeout: float, silence_seconds: float, max_seconds: float,
                     cancel: threading.Event | None = None,
                     interrupt: Callable[[], bool] | None = None, min_start_frames: int = 3) -> np.ndarray | None:
    """Wait up to start_timeout for speech, then record until silence_seconds of quiet or max_seconds.
    Recording only starts after min_start_frames consecutive speech frames (~240 ms), so a click, cough or
    keyboard tap doesn't start (and immediately end) a recording."""
    pre_roll: deque = deque(maxlen=6)
    frames: list[np.ndarray] = []
    started = False
    run = 0
    waited = silent = total = 0.0
    while True:
        if (cancel and cancel.is_set()) or (interrupt and interrupt()):
            return None
        frame = read_frame(0.3)
        if frame is None:
            waited += 0.3
            if not started and waited >= start_timeout:
                return None
            continue
        dur = len(frame) / sample_rate
        speech = vad.is_speech(frame)
        if not started:
            pre_roll.append(frame)
            waited += dur
            run = run + 1 if speech else 0
            if run >= min_start_frames:
                started = True
                frames.extend(pre_roll)
            elif waited >= start_timeout:
                return None
            continue
        frames.append(frame)
        total += dur
        silent = 0.0 if speech else silent + dur
        if silent >= silence_seconds or total >= max_seconds:
            break
    return np.concatenate(frames)


def chime(sample_rate: int = 24000) -> np.ndarray:
    """Short two-tone 'I'm listening' sound."""
    def tone(freq, dur):
        t = np.linspace(0, dur, int(sample_rate * dur), endpoint=False)
        env = np.minimum(1, np.minimum(t, dur - t) * 40)
        return np.sin(2 * np.pi * freq * t) * env
    sig = np.concatenate([tone(880, 0.07), tone(1320, 0.09)]) * 0.25
    return (sig * 32767).astype(np.int16)
