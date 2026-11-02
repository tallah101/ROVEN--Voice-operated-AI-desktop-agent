import threading
from types import SimpleNamespace

import pytest

from config import Settings
from core.conversation_manager import ConversationManager
from core.llm_gemini import (GeminiClient, LLMProviderError, from_response, rank_models, sanitize_schema,
                             to_contents, to_function_declarations)
from core.reasoning_engine import ReasoningEngine
from core.tool_registry import Tool, ToolImage, ToolRegistry
from security.audit_log import AuditLog
from security.permission_manager import PermissionManager
from storage.database import Database
from storage.memory_store import MemoryStore
from tests.fakes import FakeResponse


class FakeSession:
    def __init__(self, get=None, post=None):
        self.headers = {}
        self._get, self._post = get, post
        self.posts = []

    def get(self, url, params=None, timeout=None):
        return self._get(url, params)

    def post(self, url, json=None, timeout=None):
        self.posts.append({"url": url, "json": json})
        return self._post(url, json)


MODELS = {"models": [
    {"name": "models/gemini-3.7-flash", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-3.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-3.8-flash-preview", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-3.1-flash-image", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-3.1-pro", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
]}


def test_model_ranking_prefers_newest_stable_flash():
    names = [m["name"].split("/")[1] for m in MODELS["models"]]
    assert rank_models(names) == ["gemini-3.7-flash", "gemini-3.8-flash-preview", "gemini-3.5-flash-lite"]


def test_schema_sanitizing():
    schema = {"type": "object", "additionalProperties": False, "required": ["to", "missing"], "properties": {
        "to": {"type": "array", "items": {"type": "string", "pattern": "@"}, "maxItems": 50},
        "body": {"type": "string", "minLength": 1, "maxLength": 9},
        "action": {"enum": ["archive", "star"]},
        "n": {"type": "integer", "minimum": 1, "maximum": 3},
        "rows": {"type": "array", "items": {"type": "array"}},
        "sheets": {"type": "object", "additionalProperties": {"type": "array"}}}}
    out = sanitize_schema(schema)
    assert "additionalProperties" not in out and out["required"] == ["to"]
    assert out["properties"]["to"] == {"type": "array", "items": {"type": "string"}, "maxItems": 50}
    assert out["properties"]["body"] == {"type": "string"}
    assert out["properties"]["action"] == {"type": "string", "enum": ["archive", "star"]}
    assert out["properties"]["rows"]["items"] == {"type": "array", "items": {"type": "string"}}
    assert out["properties"]["sheets"]["type"] == "string"
    assert sanitize_schema({"type": "object", "properties": {}}) is None


def test_full_registry_translates_for_gemini():
    from automation.application_control import AppCatalog
    from automation.browser_agent import BrowserAgent
    from core.tools_builtin import build_registry
    from core.tools_general import register_general_tools
    from core.tools_integrations import register_integration_tools
    from storage.reminders import Reminders
    from storage.workflow_store import WorkflowStore
    s = Settings()
    db = Database(":memory:")
    reg = build_registry(PermissionManager(s), AuditLog(db), MemoryStore(db), AppCatalog(), WorkflowStore(db))
    register_integration_tools(reg, SimpleNamespace(), SimpleNamespace(), s, BrowserAgent(s))
    register_general_tools(reg, s, lambda p: None, Reminders(db))
    decls, json_args = to_function_declarations(reg.schemas() + [{"type": "web_search_20250305", "name": "web_search"}])
    assert len(decls) == len(reg.names())                       # server tool dropped, every real tool kept
    assert json_args == {"create_spreadsheet": {"sheets"}}

    def walk(x):
        if isinstance(x, dict):
            assert not {"additionalProperties", "pattern", "minLength", "maxLength", "cache_control"} & set(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(decls)


def test_message_translation_with_signatures_images_and_errors():
    msgs = [
        {"role": "user", "content": [{"type": "text", "text": "what's on screen?"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "Looking", "_sig": "S1"},
                                          {"type": "tool_use", "id": "c1", "name": "look_at_screen", "input": {}, "_sig": "S2"},
                                          {"type": "tool_use", "id": "c2", "name": "get_volume", "input": {}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "c1", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"}},
                {"type": "text", "text": "Screenshot 1366x768"}], "is_error": False},
            {"type": "tool_result", "tool_use_id": "c2", "content": "boom", "is_error": True}]},
        {"role": "assistant", "content": [{"type": "server_tool_use", "id": "s", "name": "web_search", "input": {}}]},
    ]
    c = to_contents(msgs)
    assert [x["role"] for x in c] == ["user", "model", "user"]
    model_parts = c[1]["parts"]
    assert model_parts[0] == {"text": "Looking", "thoughtSignature": "S1"}
    assert model_parts[1]["functionCall"] == {"name": "look_at_screen", "args": {}, "id": "c1"}
    assert model_parts[1]["thoughtSignature"] == "S2"
    user_parts = c[2]["parts"]
    assert user_parts[0]["functionResponse"] == {"name": "look_at_screen", "id": "c1", "response": {"result": "Screenshot 1366x768"}}
    assert user_parts[1]["functionResponse"]["response"] == {"error": "boom"}
    assert user_parts[2] == {"inlineData": {"mimeType": "image/jpeg", "data": "QUJD"}}


def test_response_translation():
    data = {"candidates": [{"content": {"parts": [
        {"text": "thinking...", "thought": True},
        {"functionCall": {"name": "create_spreadsheet", "args": {"path": "x", "sheets": '{"A": [["h"]]}'}},
         "thoughtSignature": "SIG"}]}}]}
    r = from_response(data, {"create_spreadsheet": {"sheets"}})
    assert r.stop_reason == "tool_use"
    b = r.content[0]
    assert b["input"]["sheets"] == {"A": [["h"]]} and b["_sig"] == "SIG" and b["id"].startswith("g_")
    with pytest.raises(LLMProviderError, match="SAFETY"):
        from_response({"promptFeedback": {"blockReason": "SAFETY"}}, {})


def test_free_quota_fallback_to_next_model_and_retry_on_rate_limit():
    calls = []

    def post(url, body):
        model = url.split("models/")[1].split(":")[0]
        calls.append(model)
        if model == "gemini-3.7-flash":
            return FakeResponse(429, {"error": {"message": "Quota exceeded ... limit: 0"}})
        if len([c for c in calls if c == model]) == 1:
            return FakeResponse(429, {"error": {"message": "slow down", "details": [{"retryDelay": "3s"}]}})
        return FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": "[lang=en] OK"}]}}]})

    waits = []
    s = Settings(llm_provider="gemini")
    client = GeminiClient("AIzaTEST", s, session=FakeSession(get=lambda u, p: FakeResponse(200, MODELS), post=post),
                          sleep=waits.append)
    r = client.messages.create(model="x", max_tokens=100, system=[{"type": "text", "text": "sys"}], tools=[],
                               messages=[{"role": "user", "content": [{"type": "text", "text": "hi"}]}])
    assert r.content[0]["text"] == "[lang=en] OK"
    assert calls == ["gemini-3.7-flash", "gemini-3.8-flash-preview", "gemini-3.8-flash-preview"]
    assert waits == [3.0] and client.active_model == "gemini-3.8-flash-preview"
    assert "gemini-3.7-flash" not in client.candidates()       # not retried for the rest of the session


def test_bad_key_message():
    s = Settings(llm_provider="gemini")
    client = GeminiClient("bad", s, session=FakeSession(get=lambda u, p: FakeResponse(400, {"error": {"message": "API key not valid"}})))
    with pytest.raises(LLMProviderError, match="rejected the Gemini API key"):
        client.candidates()


def test_engine_end_to_end_with_gemini_tool_call_and_screenshot():
    turn = {"n": 0}

    def post(url, body):
        turn["n"] += 1
        if turn["n"] == 1:
            assert body["tools"][0]["functionDeclarations"][0]["name"] == "snap"
            return FakeResponse(200, {"candidates": [{"content": {"parts": [
                {"functionCall": {"name": "snap", "args": {"n": 2}, "id": "fc1"}, "thoughtSignature": "T"}]}}]})
        parts = body["contents"][-1]["parts"]
        assert parts[0]["functionResponse"]["id"] == "fc1" and parts[1]["inlineData"]["mimeType"] == "image/jpeg"
        assert body["contents"][-2]["parts"][0]["thoughtSignature"] == "T"
        return FakeResponse(200, {"candidates": [{"content": {"parts": [
            {"text": "[lang=ur-Latn] Screen par Chrome khula hai. <speak>اسکرین پر کروم کھلا ہے۔</speak>"}]}}]})

    s = Settings(llm_provider="gemini", gemini_model="gemini-3.7-flash")
    db = Database(":memory:")
    reg = ToolRegistry(PermissionManager(s), AuditLog(db))
    reg.register(Tool("snap", "Take a screenshot", {"type": "object", "properties": {"n": {"type": "integer"}},
                                                   "required": ["n"], "additionalProperties": False},
                      lambda n: ToolImage(b"jpg", "image/jpeg", "shot")))
    client = GeminiClient("AIzaTEST", s, session=FakeSession(post=post))
    eng = ReasoningEngine(s, reg, MemoryStore(db), ConversationManager(), client=client)
    reply = eng.run("screen par kya hai?", "ur", threading.Event())
    assert reply.lang == "ur-Latn" and reply.display == "Screen par Chrome khula hai." and "کروم" in reply.speech


def test_thinking_config_per_generation():
    from core.llm_gemini import thinking_config
    assert thinking_config("gemini-3.8-flash", "low") == {"thinkingLevel": "low"}
    assert thinking_config("gemini-2.5-flash", "low") == {"thinkingBudget": 512}
    assert thinking_config("gemini-2.5-flash", "minimal") == {"thinkingBudget": 0}
    assert thinking_config("gemini-flash-latest", "low") is None
    assert thinking_config("gemini-3.8-flash", "default") is None


def test_overloaded_model_switches_immediately_and_is_tried_last():
    calls = []

    def post(url, body):
        model = url.split("models/")[1].split(":")[0]
        calls.append((model, body["generationConfig"].get("thinkingConfig")))
        if model == "gemini-3.7-flash":
            return FakeResponse(503, {"error": {"message": "This model is currently experiencing high demand."}})
        return FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": "[lang=en] OK"}]}}]})

    waits = []
    s = Settings(llm_provider="gemini")
    client = GeminiClient("AIzaTEST", s, session=FakeSession(get=lambda u, p: FakeResponse(200, MODELS), post=post),
                          sleep=waits.append)
    msgs = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
    client.messages.create(model="x", max_tokens=100, system=[], tools=[], messages=msgs)
    assert calls[0] == ("gemini-3.7-flash", {"thinkingLevel": "low"})
    assert calls[1][0] == "gemini-3.8-flash-preview" and waits == []          # no waiting on a busy model
    assert client.candidates()[-1] == "gemini-3.7-flash"                      # busy model now tried last
    calls.clear()
    client.messages.create(model="x", max_tokens=100, system=[], tools=[], messages=msgs)
    assert calls[0][0] == "gemini-3.8-flash-preview"                           # next request goes straight to it


def test_slow_model_is_demoted():
    clock = {"t": 0.0}
    import core.llm_gemini as g

    def post(url, body):
        clock["t"] += 40.0                                                     # every answer takes 40 s
        return FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

    orig = g.time.time
    g.time.time = lambda: clock["t"]
    try:
        s = Settings(llm_provider="gemini")
        client = GeminiClient("AIzaTEST", s, session=FakeSession(get=lambda u, p: FakeResponse(200, MODELS), post=post))
        client.messages.create(model="x", max_tokens=10, system=[], tools=[],
                               messages=[{"role": "user", "content": [{"type": "text", "text": "hi"}]}])
        assert client.candidates()[0] == "gemini-3.8-flash-preview"
        assert client.candidates()[-1] == "gemini-3.7-flash"
    finally:
        g.time.time = orig


def test_signature_error_retries_with_neutral_signatures():
    seen = []

    def post(url, body):
        parts = body["contents"][1]["parts"]
        seen.append(parts[0].get("thoughtSignature"))
        if len(seen) == 1:
            return FakeResponse(400, {"error": {"message": "Function call is missing a thought_signature"}})
        return FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

    s = Settings(llm_provider="gemini", gemini_model="gemini-3.7-flash")
    client = GeminiClient("AIzaTEST", s, session=FakeSession(post=post))
    msgs = [{"role": "user", "content": [{"type": "text", "text": "open notepad"}]},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "a", "name": "open_app", "input": {"name": "Notepad"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "a", "content": "ok"}]}]
    client.messages.create(model="x", max_tokens=10, system=[], tools=[], messages=msgs)
    assert seen == [None, "skip_thought_signature_validator"]


def test_speed_test_order_is_used():
    speeds = {"gemini-3.7-flash": 9.0, "gemini-3.8-flash-preview": 2.0, "gemini-3.5-flash-lite": 1.0}
    clock = {"t": 0.0}
    import core.llm_gemini as g

    def post(url, body):
        model = url.split("models/")[1].split(":")[0]
        clock["t"] += speeds[model]
        return FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": "ROVEN OK"}]}}]})

    orig = g.time.time
    g.time.time = lambda: clock["t"]
    try:
        s = Settings(llm_provider="gemini")
        client = GeminiClient("AIzaTEST", s, session=FakeSession(get=lambda u, p: FakeResponse(200, MODELS), post=post))
        timed = client.speed_test(client.candidates(), report=lambda m: None)
        assert [m for m, _ in timed] == ["gemini-3.5-flash-lite", "gemini-3.8-flash-preview", "gemini-3.7-flash"]
        s.gemini_order = [m for m, _ in timed]
        fresh = GeminiClient("AIzaTEST", s, session=FakeSession(get=lambda u, p: FakeResponse(200, MODELS), post=post))
        assert fresh.candidates()[0] == "gemini-3.5-flash-lite"
    finally:
        g.time.time = orig


def test_gemini_speech_to_text_and_fallback():
    import base64
    import io
    import wave

    import numpy as np

    from speech.speech_to_text import GeminiSpeechToText, Transcript, parse_transcript_json, wav_bytes
    audio = (np.sin(np.linspace(0, 600, 16000)) * 3000).astype(np.int16)
    wav = wav_bytes(audio)
    with wave.open(io.BytesIO(wav)) as w:
        assert w.getframerate() == 16000 and w.getnframes() == 16000

    sent = {}

    def post(url, body):
        sent.update(body)
        return FakeResponse(200, {"candidates": [{"content": {"parts": [
            {"text": '{"text": "Roven, YouTube kholo", "language": "ur"}'}]}}]})

    s = Settings(llm_provider="gemini", gemini_model="gemini-3.5-flash")
    client = GeminiClient("AIzaTEST", s, session=FakeSession(post=post))

    class Whisper:
        def transcribe(self, a):
            return Transcript("offline text", "en", 0.5)

    stt = GeminiSpeechToText(client, Whisper(), ["Mintsy", "Slack"])
    t = stt.transcribe(audio)
    assert (t.text, t.language) == ("Roven, YouTube kholo", "ur")
    part = sent["contents"][0]["parts"][0]["inlineData"]
    assert part["mimeType"] == "audio/wav" and base64.b64decode(part["data"]) == wav
    assert "Mintsy" in sent["contents"][0]["parts"][1]["text"]
    assert sent["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "minimal"}

    broken = GeminiClient("AIzaTEST", s, session=FakeSession(post=lambda u, b: FakeResponse(500, {"error": {"message": "boom"}})))
    assert GeminiSpeechToText(broken, Whisper(), []).transcribe(audio).text == "offline text"

    assert parse_transcript_json('```json\n{"text": "Chrome kholo", "language": "ur"}\n```') == ("Chrome kholo", "ur")
    assert parse_transcript_json("just text") == ("just text", "en")


def test_common_mishearings_of_roven_wake_it():
    from speech.wake_word import match_wake_phrase
    phrases = Settings().wake_phrases
    for heard, rest in [("Rowan, YouTube kholo.", "YouTube kholo"), ("Raven open Chrome", "open Chrome"),
                        ("Roben", ""), ("Ruven, volume kam karo", "volume kam karo")]:
        assert match_wake_phrase(heard, phrases) == rest, heard
    assert match_wake_phrase("let's watch a movie tonight", phrases) is None
    assert match_wake_phrase("I told Robin about the meeting yesterday", phrases) is None   # not near the start


def test_old_config_files_get_new_wake_spellings(tmp_path, monkeypatch):
    import json

    import config
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"wake_phrases": ["roven"], "llm_provider": "gemini"}), encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "models")
    s = config.load_settings()
    assert "rowan" in s.wake_phrases and s.llm_provider == "gemini"


def test_wake_word_with_lead_in():
    from speech.wake_word import match_wake_phrase
    phrases = Settings().wake_phrases
    assert match_wake_phrase("Hey Roven, open Slack", phrases) == "open Slack"
    assert match_wake_phrase("Oye Rowan Chrome kholo", phrases) == "Chrome kholo"
    assert match_wake_phrase("Ro ven, volume up", phrases) == "volume up"
    assert match_wake_phrase("Hey, I told Robin", phrases) is None
