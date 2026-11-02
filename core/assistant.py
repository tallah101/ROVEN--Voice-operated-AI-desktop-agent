"""ROVEN orchestrator: standby -> wake -> listen -> think/act -> speak -> follow-up -> standby.

Runs on its own thread. Talks to the GUI only through ui_queue messages (kind, payload)."""
from __future__ import annotations

import logging
import queue
import threading
import time

from automation.application_control import AppCatalog
from automation.browser_agent import BrowserAgent
from config import DB_PATH
from core.conversation_manager import ConversationManager
from core.phrases import is_dismissal, parse_yes_no
from core.reasoning_engine import ReasoningEngine
from core.reply_format import Reply, base_lang
from core.tools_builtin import build_registry
from core.tools_general import register_general_tools
from core.tools_integrations import register_integration_tools
from core.workflows import Workflows
from integrations.manager import Integrations
from security.audit_log import AuditLog
from security.permission_manager import PermissionManager
from speech.audio_processing import EnergyVAD, chime, record_utterance
from speech.microphone import Microphone
from speech.speech_to_text import SpeechToText, Transcript
from speech.text_to_speech import TextToSpeech
from speech.wake_word import create_detector
from storage.database import Database
from storage.memory_store import MemoryStore
from storage.conversation_log import DailyConversationLog
from storage.reminders import Reminders
from storage.workflow_store import WorkflowStore

log = logging.getLogger(__name__)

CONFIRM_PROMPT = {
    "en": "Please confirm: {}. Yes or no?",
    "ur": "تصدیق کریں: {}۔ ہاں یا نہیں؟",
    "hi": "कृपया पुष्टि करें: {}. हाँ या नहीं?",
}
GOODBYE = {"en": "Okay.", "ur": "ٹھیک ہے۔", "hi": "ठीक है।"}
WORKING = {
    "en": "Working on it, this may take a moment.",
    "ur": "کام شروع کر دیا ہے، تھوڑا وقت لگ سکتا ہے۔",
    "hi": "काम शुरू कर दिया है, थोड़ा समय लग सकता है।",
}


class Assistant(threading.Thread):
    def __init__(self, settings, ui_queue: queue.Queue, api_key: str) -> None:
        super().__init__(daemon=True, name="roven-assistant")
        self.settings = settings
        self.ui_queue = ui_queue
        self.db = Database(DB_PATH)
        self.audit = AuditLog(self.db)
        self.memory = MemoryStore(self.db)
        self.workflow_store = WorkflowStore(self.db)
        interrupted = self.workflow_store.mark_interrupted_on_startup()
        if interrupted:
            log.info("%d task(s) were interrupted by the last shutdown", interrupted)
        self.catalog = AppCatalog()
        self.integrations = Integrations(settings)
        self.workflows = Workflows(self.integrations, settings)
        self.browser = BrowserAgent(settings)
        self.cancel = threading.Event()
        self._manual = threading.Event()
        self._quit = threading.Event()
        self._gui_answer: queue.Queue = queue.Queue()
        self._lang = "en"
        self.mic = Microphone(settings.sample_rate, settings.mic_device)
        self.stt = SpeechToText(settings.stt_model, settings.stt_device, settings.stt_compute_type, settings.vocabulary)
        self.tts = TextToSpeech(settings)
        self.permissions = PermissionManager(settings, confirm=self._confirm)
        self.registry = build_registry(self.permissions, self.audit, self.memory, self.catalog, self.workflow_store)
        register_integration_tools(self.registry, self.integrations, self.workflows, settings, self.browser)
        self.reminders = Reminders(self.db)
        register_general_tools(self.registry, settings, show=lambda payload: self.ui("show", payload),
                               reminders=self.reminders)
        self.chat_log = DailyConversationLog(settings)
        self.registry.observers.append(self._log_action)
        self._last_reminder_check = 0.0
        self._ready = threading.Event()
        self.conversation = ConversationManager()
        client = None
        if settings.llm_provider == "gemini":
            from core.llm_gemini import GeminiClient
            client = GeminiClient(api_key, settings, status=lambda msg: self.ui("processing", msg))
            if settings.stt_engine in ("auto", "gemini"):
                from speech.speech_to_text import GeminiSpeechToText
                self.stt = GeminiSpeechToText(client, self.stt, settings.vocabulary, settings.sample_rate)
        self.engine = ReasoningEngine(settings, self.registry, self.memory, self.conversation, api_key,
                                      integrations=self.integrations, workflow_store=self.workflow_store, client=client)
        self._announced = False
        self.wake = None

    # ---- public, thread-safe controls ------------------------------------------------------------
    def activate(self) -> None:
        self._manual.set()

    def emergency_stop(self) -> None:
        self.cancel.set()
        self.tts.stop()
        self.audit.record("emergency_stop")
        self.ui("error", "Emergency stop — all actions halted.")

    def answer_confirmation(self, yes: bool) -> None:
        self._gui_answer.put(yes)

    def set_privacy(self, enabled: bool) -> None:
        self.settings.privacy_mode = enabled
        if enabled:
            self.emergency_stop()

    def shutdown(self) -> None:
        self._quit.set()
        self.cancel.set()
        self.tts.stop()

    def ui(self, kind: str, payload=None) -> None:
        self.ui_queue.put((kind, payload))

    # ---- main loop -------------------------------------------------------------------------------
    def run(self) -> None:
        try:
            self.wake = create_detector(self.settings)
            self.ui("info", f"Wake engine: {self.wake.name}")
            threading.Thread(target=self._warm_up, daemon=True).start()
        except Exception as exc:
            log.exception("Startup failed")
            self.ui("error", f"Startup failed: {exc}")
            return
        while not self._quit.is_set():
            if self.settings.privacy_mode:
                if self.mic.running:
                    self.mic.stop()
                if self._manual.is_set():
                    self._manual.clear()
                    self.ui("error", "Privacy mode is on — the microphone is off.")
                time.sleep(0.3)
                continue
            if not self.mic.running:
                try:
                    self.mic.start()
                except Exception as exc:
                    log.exception("Microphone failed")
                    self.ui("error", f"Microphone unavailable: {exc}")
                    time.sleep(5)
                    continue
            if self._manual.is_set():
                self._manual.clear()
                self._session(None)
                continue
            self._fire_reminders()
            frame = self.mic.read(0.3)
            if frame is None:
                continue
            try:
                hit = self.wake.process(frame)
            except Exception:
                log.exception("Wake detector error")
                continue
            if hit is not None:
                self.audit.record("wake", detail=self.wake.name)
                self._session(hit or None)
        self.mic.stop()
        try:
            self.browser.close()
        except Exception:
            log.debug("Browser close failed", exc_info=True)
        self.db.close()

    def _safe_log(self, fn, *args) -> None:
        try:
            fn(*args)
        except Exception:
            log.warning("Could not write the daily conversation log", exc_info=True)

    def _log_action(self, name: str, summary: str, ok: bool, status: str) -> None:
        if name in ("look_at_screen", "move_mouse_to", "show_results"):
            return                                            # too chatty for the daily log
        self._safe_log(self.chat_log.action, name, summary.split("\n")[0], ok, status)

    def _fire_reminders(self) -> None:
        if time.time() - self._last_reminder_check < 20:
            return
        self._last_reminder_check = time.time()
        try:
            due = self.reminders.due_now()
        except Exception:
            return
        for rem in due:
            self.reminders.mark_done(rem["id"])
            text = f"Reminder: {rem['message']}"
            self.ui("speaking", text)
            self._safe_log(self.chat_log.roven, text)
            self._say(Reply(text, text, "en" if rem["message"].isascii() else self._lang))
            self.ui("standby")

    def _warm_up(self) -> None:
        try:
            self.stt.load()
            self._ready.set()
            self.catalog.refresh()
            self.ui("info", "Ready")
        except Exception as exc:
            log.exception("Warm-up failed")
            self.ui("error", f"Speech model failed to load: {exc}")

    # ---- one conversation ------------------------------------------------------------------------
    def _session(self, initial_text: str | None) -> None:
        self.cancel.clear()
        self.ui("wake")
        self._safe_log(self.chat_log.session_start)
        try:
            if not self._ready.is_set():
                self.ui("processing", "Loading the speech model (first start can take a few minutes)…")
                while not self._ready.wait(0.5):
                    if self.cancel.is_set() or self._quit.is_set():
                        return
            if self.settings.chime:
                self._play_chime()
            text: str | None = initial_text
            lang: str | None = None
            if initial_text and getattr(self.wake, "last_audio", None) is not None:
                # "Roven, YouTube kholo" in one breath: transcribe the whole clip with the accurate recogniser
                self.ui("transcribing", initial_text)
                full = self.stt.transcribe(self.wake.last_audio)
                self.wake.last_audio = None
                from speech.wake_word import match_wake_phrase
                rest = match_wake_phrase(full.text, self.settings.wake_phrases, threshold=0.6)
                text, lang = (rest if rest is not None else full.text) or None, full.language
            first = True
            misses = 0
            while not self.cancel.is_set() and not self._quit.is_set():
                if text is None:
                    self.ui("listening")
                    t = self._listen(self.settings.listen_timeout_seconds if first else self.settings.follow_up_seconds)
                    if t is None:
                        break
                    if not t.text.strip():
                        misses += 1                     # only noise was captured: keep listening, don't give up
                        if misses > 2:
                            break
                        self.ui("listening", "Didn't catch that — please say it again.")
                        continue
                    misses = 0
                    text, lang = t.text, t.language
                first = False
                self.ui("transcript", text)
                log.info("Heard (%s): %s", lang or "?", text)
                self._safe_log(self.chat_log.user, text, lang)
                if is_dismissal(text):
                    self._say(Reply(GOODBYE.get(base_lang(lang), "Okay."), GOODBYE.get(base_lang(lang), "Okay."), lang or "en"))
                    break
                if lang:
                    self._lang = lang
                self.ui("processing")
                self.audit.record("user_request", detail=text)
                self._announced = False
                started = time.time()
                log.info("Thinking with %s…", self.settings.llm_provider)
                reply = self.engine.run(text, lang, self.cancel, on_progress=self._progress)
                log.info("Reply after %.1fs [%s]: %s", time.time() - started, reply.lang, reply.display[:300])
                if self.cancel.is_set():
                    break
                self._lang = reply.lang
                self._safe_log(self.chat_log.roven, reply.display)
                self.ui("speaking", reply.display)
                self._say(reply)
                text = None
            if not self.cancel.is_set():
                self.ui("done")
        except Exception as exc:
            log.exception("Session failed")
            self.ui("error", str(exc))
            try:
                self._say(Reply("Sorry, something went wrong.", "Sorry, something went wrong.", "en"))
            except Exception:
                pass
        finally:
            self.mic.drain()
            if self.wake:
                self.wake.reset()
            self.ui("standby")

    def _progress(self, summary: str, long_running: bool) -> None:
        log.info("Action: %s", summary.split("\n")[0])
        self.ui("executing", summary)
        if long_running and not self._announced:
            self._announced = True
            lang = base_lang(self._lang)
            msg = WORKING.get(lang, WORKING["en"])
            self._say(Reply(msg, msg, lang if lang in WORKING else "en"))
            self.ui("executing", summary)

    def _listen(self, timeout: float, interrupt=None) -> Transcript | None:
        self.mic.drain()
        audio = record_utterance(self.mic.read, EnergyVAD(), self.settings.sample_rate, timeout,
                                 self.settings.silence_seconds, self.settings.max_utterance_seconds,
                                 cancel=self.cancel, interrupt=interrupt)
        if audio is None:
            return None
        self.ui("transcribing")
        return self.stt.transcribe(audio)

    def _say(self, reply: Reply) -> None:
        self.mic.muted = True        # don't hear ourselves
        try:
            self.tts.speak(reply.speech, reply.lang)
        finally:
            time.sleep(0.15)
            self.mic.drain()
            self.mic.muted = False

    def _play_chime(self) -> None:
        self.mic.muted = True
        try:
            self.tts.play(chime(), 24000)
        except Exception:
            log.debug("Chime failed", exc_info=True)
        finally:
            self.mic.drain()
            self.mic.muted = False

    # ---- confirmations (called by PermissionManager from this same thread) ----------------------
    def _confirm(self, summary: str) -> bool:
        while not self._gui_answer.empty():
            self._gui_answer.get_nowait()
        self.ui("confirm", summary)
        lang = base_lang(self._lang)
        spoken = summary.split("\n")[0]                  # never read code aloud; the dock shows the details
        question = CONFIRM_PROMPT.get(lang, CONFIRM_PROMPT["en"]).format(spoken)
        self._safe_log(self.chat_log.write, "ROVEN", f"Asked permission: {spoken}")
        self._say(Reply(question, question, lang if lang in CONFIRM_PROMPT else "en"))
        for _ in range(2):
            t = self._listen(8, interrupt=lambda: not self._gui_answer.empty())
            if not self._gui_answer.empty():
                answer = self._gui_answer.get_nowait()
                self.audit.record("confirmation", detail=f"{summary} -> {'yes' if answer else 'no'} (click)")
                return answer
            if t is None:
                break
            answer = parse_yes_no(t.text)
            if answer is not None:
                self._safe_log(self.chat_log.user, t.text)
                self.audit.record("confirmation", detail=f"{summary} -> {'yes' if answer else 'no'} (voice)")
                self.ui("executing", summary if answer else "Cancelled")
                return answer
            self._say(Reply("Please say yes or no.", "Please say yes or no.", "en"))
        self.audit.record("confirmation", detail=f"{summary} -> no answer, treated as no")
        return False
