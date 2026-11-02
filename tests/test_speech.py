import numpy as np

from speech.audio_processing import EnergyVAD, chime, record_utterance
from speech.wake_word import match_wake_phrase

PHRASES = ["roven", "rovan", "روون"]


def test_wake_phrase_with_trailing_command():
    assert match_wake_phrase("Roven, open Chrome.", PHRASES) == "open Chrome"
    assert match_wake_phrase("Rovan Gmail kholo", PHRASES) == "Gmail kholo"
    assert match_wake_phrase("Ro ven, volume kam karo", PHRASES) == "volume kam karo"
    assert match_wake_phrase("روون، ای میلز چیک کرو", PHRASES) == "ای میلز چیک کرو"
    assert match_wake_phrase("Roven.", PHRASES) == ""


def test_wake_phrase_rejects_other_speech():
    assert match_wake_phrase("let's move on to the next item", PHRASES) is None
    assert match_wake_phrase("I was talking about Roven yesterday in the meeting", PHRASES) is None


def _frames(levels, n=1280):
    rng = np.random.default_rng(0)
    return [(rng.standard_normal(n) * lv).astype(np.int16) for lv in levels]


def test_record_utterance_stops_on_silence():
    frames = _frames([50] * 5 + [4000] * 10 + [50] * 30)
    it = iter(frames)
    audio = record_utterance(lambda t: next(it, None), EnergyVAD(), 16000, 3, 1.0, 20)
    assert audio is not None and 10 * 1280 <= len(audio) <= 30 * 1280


def test_record_utterance_times_out_without_speech():
    it = iter(_frames([50] * 100))
    assert record_utterance(lambda t: next(it, None), EnergyVAD(), 16000, 2, 1.0, 20) is None


def test_chime_is_valid_audio():
    c = chime()
    assert c.dtype == np.int16 and 0 < len(c) < 24000


def test_short_noise_does_not_start_recording():
    # one loud click, then quiet, then real speech
    frames = _frames([50] * 3 + [5000] + [50] * 5 + [4000] * 10 + [50] * 30)
    it = iter(frames)
    audio = record_utterance(lambda t: next(it, None), EnergyVAD(), 16000, 5, 1.0, 20)
    assert audio is not None and len(audio) >= 10 * 1280          # captured the speech, not just the click


def test_only_clicks_times_out():
    frames = _frames(([50] * 4 + [5000]) * 12)
    it = iter(frames)
    assert record_utterance(lambda t: next(it, None), EnergyVAD(), 16000, 3, 1.0, 20) is None
