"""ROVEN configuration. User settings live as JSON in %APPDATA%\\ROVEN."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

log = logging.getLogger(__name__)

APP_NAME = "ROVEN"
APP_DIR = Path(os.environ.get("APPDATA") or (Path.home() / ".config")) / APP_NAME
CONFIG_PATH = APP_DIR / "config.json"
DB_PATH = APP_DIR / "roven.db"
LOG_PATH = APP_DIR / "roven.log"
MODELS_DIR = APP_DIR / "models"
KEYRING_SERVICE = "ROVEN"

# Microsoft neural voices used by edge-tts. Override in config.json if you prefer others.
DEFAULT_VOICES = {
    "en": "en-US-GuyNeural",
    "ur": "ur-PK-UzmaNeural",
    "hi": "hi-IN-SwaraNeural",
    "pa": "ur-PK-UzmaNeural",   # no Punjabi neural voice in edge-tts; Shahmukhi is read by the Urdu voice
    "ar": "ar-SA-ZariyahNeural",
    "es": "es-ES-ElviraNeural",
    "fr": "fr-FR-DeniseNeural",
    "de": "de-DE-KatjaNeural",
    "zh": "zh-CN-XiaoxiaoNeural",
    "ja": "ja-JP-NanamiNeural",
}

DEFAULT_CLICKUP_PREFIXES = {
    "NR": "New Requirement", "CR": "Client Request", "CF": "Change Functionality",
    "BF": "Bug Fix", "UI": "UI Change", "UX": "UX Change", "IMP": "Improvement",
    "INV": "Investigation", "DOC": "Documentation",
}


@dataclass
class Settings:
    # Wake word
    wake_engine: str = "openwakeword"          # openwakeword | porcupine | whisper_keyword
    wake_model_path: str = ""                  # custom "roven" .onnx (openWakeWord) or .ppn (Porcupine)
    wake_threshold: float = 0.5                # openWakeWord score threshold (higher = fewer false wakes)
    porcupine_sensitivity: float = 0.6
    wake_phrases: list = field(default_factory=lambda: [
        "roven", "rovan", "rovin", "rowan", "rowen", "ruven", "roben", "roban", "raven", "rawan", "rovn",
        "روون", "روین", "रोवन", "रोवेन"])
    stt_engine: str = "auto"                   # auto (Gemini when Gemini is the AI) | gemini | whisper
    keyword_model: str = "tiny"                # Whisper size for the whisper_keyword fallback
    # Audio / speech recognition
    mic_device: int | None = None
    sample_rate: int = 16000
    stt_model: str = "small"                   # tiny | base | small | medium | large-v3
    stt_device: str = "auto"                   # auto | cpu | cuda
    stt_compute_type: str = "int8"
    vocabulary: list = field(default_factory=lambda: ["Roven", "Slack", "Gmail", "ClickUp", "Mintsy"])
    silence_seconds: float = 1.0
    max_utterance_seconds: float = 25.0
    listen_timeout_seconds: float = 7.0
    follow_up_seconds: float = 6.0
    # AI
    llm_provider: str = "anthropic"            # anthropic | gemini
    llm_model: str = "claude-sonnet-5-5"       # Anthropic model
    gemini_model: str = "auto"                 # "auto" picks the best free Flash model your key can use
    gemini_thinking: str = "low"               # minimal | low | medium | high | default — lower = much faster replies
    gemini_slow_seconds: float = 25.0          # a model slower than this is tried last next time
    gemini_order: list = field(default_factory=list)   # fastest-first order from the speed test (configure_ai.py)
    llm_max_tokens: int = 8000
    enable_web_research: bool = True           # Anthropic server-side web search for research tasks
    max_tool_steps: int = 40
    response_language: str = "auto"            # auto, or e.g. "ur-Latn", "en"
    # Voice output
    tts_engine: str = "edge"                   # edge (neural, online) | sapi (offline Windows voices)
    tts_rate: str = "+0%"
    voices: dict = field(default_factory=lambda: dict(DEFAULT_VOICES))
    chime: bool = True
    # Behaviour & security
    privacy_mode: bool = False
    trusted_actions: list = field(default_factory=list)   # medium-risk tool names allowed without asking
    emergency_hotkey: str = "ctrl+alt+shift+x"
    manual_hotkey: str = "ctrl+alt+space"
    onboarded: bool = False
    # Browser agent
    browser_channel: str = "msedge"            # msedge | chrome | chromium (Playwright's own)
    # Documents & reports
    report_folder: str = "~/Documents/ROVEN Reports"
    # Integrations
    google_client_secrets_path: str = ""
    trusted_email_domains: list = field(default_factory=list)   # e.g. ["mycompany.com"]; empty = always confirm
    slack_briefing_channels: list = field(default_factory=list)
    clickup_team_id: str = ""
    clickup_title_format: str = "{prefix} - {title}"
    clickup_prefixes: dict = field(default_factory=lambda: dict(DEFAULT_CLICKUP_PREFIXES))
    stale_task_days: int = 5
    # Daily conversation log (plain text, one file per day)
    daily_log_enabled: bool = True
    daily_log_folder: str = ""                 # empty = your Windows Documents folder
    daily_log_name: str = "Roven ({date})"
    daily_log_date_format: str = "%d-%m-%Y"    # -> "Roven (02-11-2026).txt"
    # General PC control
    script_timeout_seconds: int = 120
    screenshot_max_width: int = 1366


def ensure_app_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    ensure_app_dir()
    settings = Settings()
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            known = {f.name for f in fields(Settings)}
            for key, value in data.items():
                if key in known:
                    setattr(settings, key, value)
        except Exception:
            log.exception("Could not read %s; using defaults", CONFIG_PATH)
    for phrase in Settings().wake_phrases:          # new default spellings reach older config files too
        if phrase not in settings.wake_phrases:
            settings.wake_phrases.append(phrase)
    return settings


def save_settings(settings: Settings) -> None:
    ensure_app_dir()
    CONFIG_PATH.write_text(json.dumps(asdict(settings), indent=2, ensure_ascii=False), encoding="utf-8")
