"""Google Gemini as ROVEN's brain.

GeminiClient mimics the small part of the Anthropic client the reasoning engine uses
(client.messages.create(...)), translating requests and responses both ways, so the rest of ROVEN —
tools, permissions, logs, workflows — works unchanged with either provider.

* Model "auto": lists the models your key can use and picks the newest stable Flash model; if Google
  says that model has no free quota, it falls back to the next one (e.g. Flash-Lite) automatically.
* Thought signatures (needed by Gemini 3+ for multi-step tool use) are preserved across turns.
* Screenshots from tools are sent as images next to the tool result.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from types import SimpleNamespace

import requests

log = logging.getLogger(__name__)
BASE = "https://generativelanguage.googleapis.com/v1beta/"
EXCLUDE = ("image", "tts", "live", "audio", "embedding", "native", "computer-use", "robotics", "veo", "imagen",
           "learnlm", "gemma", "aqa", "exp-")


class LLMProviderError(RuntimeError):
    """Error with a message that can be spoken to the user as-is."""


# ---- schema translation ------------------------------------------------------------------------------
def sanitize_schema(schema: dict) -> dict | None:
    """JSON Schema → the OpenAPI subset Gemini accepts. Returns None for objects without properties."""
    out: dict = {}
    if "description" in schema:
        out["description"] = schema["description"]
    if "enum" in schema:
        return {**out, "type": "string", "enum": [str(e) for e in schema["enum"]]}
    t = schema.get("type", "string")
    out["type"] = t
    if t == "object":
        props = {}
        for name, sub in (schema.get("properties") or {}).items():
            clean = sanitize_schema(sub)
            props[name] = clean if clean is not None else {
                "type": "string", "description": (sub.get("description", "") + " JSON-encoded object.").strip()}
        if not props:
            return None
        out["properties"] = props
        req = [r for r in schema.get("required", []) if r in props]
        if req:
            out["required"] = req
    elif t == "array":
        items = schema.get("items")
        clean = sanitize_schema(items) if isinstance(items, dict) and items else None
        if clean is None:
            clean = {"type": "string"}
        out["items"] = clean
        for k in ("minItems", "maxItems"):
            if k in schema:
                out[k] = schema[k]
    elif t in ("integer", "number"):
        for k in ("minimum", "maximum"):
            if k in schema:
                out[k] = schema[k]
    return out


def json_string_args(schema: dict) -> set[str]:
    """Top-level arguments that had to be sent to Gemini as JSON strings (objects without fixed properties)."""
    return {name for name, sub in (schema.get("properties") or {}).items()
            if sub.get("type") == "object" and not sub.get("properties")}


def to_function_declarations(tools: list[dict]) -> tuple[list[dict], dict[str, set[str]]]:
    decls, json_args = [], {}
    for t in tools:
        if "input_schema" not in t:          # Anthropic server tools (web_search) have no Gemini equivalent here
            continue
        d = {"name": t["name"], "description": t["description"]}
        params = sanitize_schema(t["input_schema"])
        if params is not None:
            d["parameters"] = params
        decls.append(d)
        stringified = json_string_args(t["input_schema"])
        if stringified:
            json_args[t["name"]] = stringified
    return decls, json_args


# ---- message translation -----------------------------------------------------------------------------
def to_contents(messages: list[dict]) -> list[dict]:
    names: dict[str, str] = {}
    contents = []
    for msg in messages:
        role = "model" if msg["role"] == "assistant" else "user"
        parts, extra = [], []
        for b in msg["content"]:
            kind = b.get("type")
            if kind == "text" and b.get("text"):
                p = {"text": b["text"]}
                if b.get("_sig"):
                    p["thoughtSignature"] = b["_sig"]
                parts.append(p)
            elif kind == "tool_use":
                names[b["id"]] = b["name"]
                p = {"functionCall": {"name": b["name"], "args": b.get("input") or {}, "id": b["id"]}}
                if b.get("_sig"):
                    p["thoughtSignature"] = b["_sig"]
                parts.append(p)
            elif kind == "tool_result":
                content = b.get("content")
                if isinstance(content, list):
                    text = "\n".join(x.get("text", "") for x in content if x.get("type") == "text")
                    for x in content:
                        if x.get("type") == "image":
                            extra.append({"inlineData": {"mimeType": x["source"]["media_type"], "data": x["source"]["data"]}})
                else:
                    text = content or ""
                key = "error" if b.get("is_error") else "result"
                parts.append({"functionResponse": {"name": names.get(b["tool_use_id"], "tool"), "id": b["tool_use_id"],
                                                   "response": {key: text}}})
            # Anthropic-only blocks (server web search etc.) are skipped
        parts += extra
        if parts:
            if contents and contents[-1]["role"] == role:
                contents[-1]["parts"].extend(parts)
            else:
                contents.append({"role": role, "parts": parts})
    return contents


def from_response(data: dict, json_args: dict[str, set[str]]) -> SimpleNamespace:
    cands = data.get("candidates") or []
    if not cands:
        reason = (data.get("promptFeedback") or {}).get("blockReason", "unknown")
        raise LLMProviderError(f"Gemini declined to answer that request (reason: {reason}).")
    cand = cands[0]
    blocks = []
    for p in (cand.get("content") or {}).get("parts", []):
        if p.get("thought"):
            continue
        if "functionCall" in p:
            fc = p["functionCall"]
            args = dict(fc.get("args") or {})
            for name in json_args.get(fc["name"], ()):
                if isinstance(args.get(name), str):
                    try:
                        args[name] = json.loads(args[name])
                    except ValueError:
                        pass
            b = {"type": "tool_use", "id": fc.get("id") or f"g_{uuid.uuid4().hex[:12]}", "name": fc["name"], "input": args}
            if p.get("thoughtSignature"):
                b["_sig"] = p["thoughtSignature"]
            blocks.append(b)
        elif "text" in p:
            b = {"type": "text", "text": p["text"]}
            if p.get("thoughtSignature"):
                b["_sig"] = p["thoughtSignature"]
            blocks.append(b)
    if not blocks:
        finish = cand.get("finishReason", "")
        msg = "Gemini stopped without an answer" + (f" ({finish})" if finish else "") + ". Please rephrase."
        blocks = [{"type": "text", "text": msg}]
    stop = "tool_use" if any(b["type"] == "tool_use" for b in blocks) else "end_turn"
    return SimpleNamespace(content=blocks, stop_reason=stop)


# ---- thinking (speed) -----------------------------------------------------------------------------
THINKING_BUDGET_25 = {"minimal": 0, "low": 512, "medium": 2048, "high": 8192}
BUSY_WORDS = ("high demand", "overloaded", "unavailable", "try again later")


def thinking_config(model: str, level: str) -> dict | None:
    """Gemini 3+ uses thinkingLevel; Gemini 2.5 uses a token budget. Less thinking = faster answers."""
    if not level or level == "default":
        return None
    m = re.search(r"gemini-(\d+)(?:\.(\d+))?", model)
    if not m:
        return None
    major = int(m.group(1))
    if major >= 3:
        return {"thinkingLevel": level}
    if major == 2 and m.group(2) == "5":
        return {"thinkingBudget": THINKING_BUDGET_25.get(level, 512)}
    return None


# ---- model choice ------------------------------------------------------------------------------------
def rank_models(names: list[str]) -> list[str]:
    def version(n):
        m = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
        return float(m.group(1)) if m else 0.0

    usable = [n for n in names if "gemini" in n and "flash" in n and not any(x in n for x in EXCLUDE)]
    # Prefer: full Flash over Lite, stable over preview, then the newest version.
    return sorted(usable, key=lambda n: ("lite" in n, "preview" in n, -version(n), n))


class _Messages:
    def __init__(self, client):
        self._c = client

    def create(self, *, model, max_tokens, system, tools, messages, **_):
        return self._c.create(max_tokens=max_tokens, system=system, tools=tools, messages=messages)


class GeminiClient:
    MAX_TOTAL_WAIT = 45.0     # seconds of rate-limit waiting per request before telling the user

    def __init__(self, api_key: str, settings, session=None, sleep=time.sleep, status=None) -> None:
        if not api_key:
            raise LLMProviderError("No Gemini API key is saved. Run scripts\\configure_ai.py gemini.")
        self.settings = settings
        self.session = session or requests.Session()
        self.session.headers["x-goog-api-key"] = api_key
        self.sleep = sleep
        self.messages = _Messages(self)
        self._candidates: list[str] | None = None
        self._lock = threading.Lock()
        self.active_model: str | None = None
        self.status = status or (lambda msg: None)
        self._no_thinking_cfg: set[str] = set()     # models that rejected a thinking setting

    # -- models
    def list_models(self) -> list[str]:
        names, token = [], None
        for _ in range(5):
            params = {"pageSize": 200, **({"pageToken": token} if token else {})}
            r = self.session.get(BASE + "models", params=params, timeout=30)
            if r.status_code in (400, 401, 403):
                raise LLMProviderError("Google rejected the Gemini API key. Check it in Google AI Studio and save it again.")
            if r.status_code != 200:
                raise LLMProviderError(f"Couldn't list Gemini models (HTTP {r.status_code}): {_error(r)['message'][:160]}")
            data = r.json()
            names += [m["name"].split("/", 1)[-1] for m in data.get("models", [])
                      if "generateContent" in m.get("supportedGenerationMethods", [])]
            token = data.get("nextPageToken")
            if not token:
                break
        return names

    def candidates(self) -> list[str]:
        with self._lock:
            if self._candidates is None:
                wanted = (self.settings.gemini_model or "auto").strip()
                if wanted != "auto":
                    self._candidates = [wanted]
                else:
                    ranked = rank_models(self.list_models())
                    if not ranked:
                        raise LLMProviderError("Your Gemini key has no Flash models available.")
                    preferred = [m for m in getattr(self.settings, "gemini_order", []) if m in ranked]
                    self._candidates = (preferred + [m for m in ranked if m not in preferred])[:6]
                log.info("Gemini model candidates: %s", self._candidates)
            return self._candidates

    def speed_test(self, models: list[str], report=print) -> list[tuple[str, float]]:
        """Time a tiny request on each model (with ROVEN's thinking setting). Returns [(model, seconds)], fastest first;
        models that fail are left out."""
        results = []
        level = getattr(self.settings, "gemini_thinking", "low")
        for model in models:
            gen = {"maxOutputTokens": 200}
            cfg = thinking_config(model, level)
            if cfg:
                gen["thinkingConfig"] = cfg
            body = {"contents": [{"role": "user", "parts": [{"text": "Reply with exactly: ROVEN OK"}]}], "generationConfig": gen}
            t0 = time.time()
            try:
                r = self.session.post(f"{BASE}models/{model}:generateContent", json=body, timeout=(10, 60))
                secs = time.time() - t0
                if r.status_code == 200:
                    results.append((model, secs))
                    report(f"    {model:28s} {secs:5.1f}s")
                else:
                    report(f"    {model:28s} unavailable ({_error(r)['message'][:60]})")
            except requests.exceptions.RequestException:
                report(f"    {model:28s} no answer")
        return sorted(results, key=lambda x: x[1])

    def transcribe_audio(self, wav: bytes, prompt: str) -> str:
        """Speech → text with the fastest available model (minimal thinking, one quick try per model)."""
        import base64
        body = {"contents": [{"role": "user", "parts": [
                    {"inlineData": {"mimeType": "audio/wav", "data": base64.b64encode(wav).decode()}},
                    {"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 400, "responseMimeType": "application/json"}}
        last = "no model available"
        for model in list(self.candidates())[:3]:
            cfg = thinking_config(model, "minimal" if model.startswith("gemini-3") else "low")
            gen = dict(body["generationConfig"], **({"thinkingConfig": cfg} if cfg and model not in self._no_thinking_cfg else {}))
            try:
                r = self.session.post(f"{BASE}models/{model}:generateContent", json={**body, "generationConfig": gen},
                                      timeout=(10, 30))
            except requests.exceptions.RequestException as exc:
                last = str(exc)
                continue
            if r.status_code == 200:
                parts = (((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
                return "".join(p.get("text", "") for p in parts if not p.get("thought"))
            err = _error(r)
            last = err["message"][:160]
            if r.status_code == 400 and "thinking" in last.lower():
                self._no_thinking_cfg.add(model)
                continue
            if r.status_code == 503 or any(w in last.lower() for w in BUSY_WORDS):
                self._demote(model, "overloaded")
        raise LLMProviderError(f"Gemini couldn't transcribe the audio: {last}")

    def _demote(self, model: str, reason: str) -> None:
        """Try this model last from now on (it may recover later, so it is kept)."""
        with self._lock:
            if self._candidates and model in self._candidates and len(self._candidates) > 1:
                self._candidates.remove(model)
                self._candidates.append(model)
                log.info("Gemini %s moved to the end of the list: %s. Order now: %s", model, reason, self._candidates)

    # -- generation
    def create(self, *, max_tokens, system, tools, messages) -> SimpleNamespace:
        system_text = "\n\n".join(b["text"] for b in system) if isinstance(system, list) else (system or "")
        decls, json_args = to_function_declarations(tools)
        body = {
            "systemInstruction": {"parts": [{"text": system_text}]},
            "contents": to_contents(messages),
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        level = getattr(self.settings, "gemini_thinking", "low")
        if decls:
            body["tools"] = [{"functionDeclarations": decls}]
            body["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}
        last_error = "unknown error"
        waited = 0.0
        for model in list(self.candidates()):
            cfg = None if model in self._no_thinking_cfg else thinking_config(model, level)
            gen = dict(body["generationConfig"])
            if cfg:
                gen["thinkingConfig"] = cfg
            else:
                gen.pop("thinkingConfig", None)
            request = {**body, "generationConfig": gen}
            for attempt in range(4):
                try:
                    t0 = time.time()
                    log.info("Asking Gemini (%s)…", model)
                    payload = {k: v for k, v in request.items() if not k.startswith("_")}
                    r = self.session.post(f"{BASE}models/{model}:generateContent", json=payload, timeout=(10, 90))
                    elapsed = time.time() - t0
                    log.info("Gemini answered in %.1fs (HTTP %s)", elapsed, r.status_code)
                except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
                    if attempt == 3:
                        raise LLMProviderError("I can't reach Gemini. Please check the internet connection.")
                    self.sleep(2 ** attempt)
                    continue
                if r.status_code == 200:
                    if self.active_model != model:
                        log.info("Using Gemini model %s", model)
                        self.active_model = model
                    if elapsed > getattr(self.settings, "gemini_slow_seconds", 25.0):
                        self._demote(model, f"slow ({elapsed:.0f}s)")
                    return from_response(r.json(), json_args)
                err = _error(r)
                last_error = err["message"]
                if r.status_code == 400 and "signature" in err["message"].lower() and not request.get("_sig_fixed"):
                    # history came from a different model (after a switch): use Google's documented bypass value
                    log.info("Retrying %s with neutral thought signatures (model was switched mid-task)", model)
                    request = {**request, "contents": _neutral_signatures(request["contents"]), "_sig_fixed": True}
                    continue
                if r.status_code == 400 and "thinking" in err["message"].lower() and cfg:
                    log.info("%s doesn't accept the thinking setting; retrying without it", model)
                    self._no_thinking_cfg.add(model)
                    request = {**body, "generationConfig": dict(body["generationConfig"])}
                    cfg = None
                    continue
                busy = r.status_code == 503 or any(w in err["message"].lower() for w in BUSY_WORDS)
                if busy and len(self.candidates()) > 1:
                    log.warning("Gemini %s is overloaded; switching to the next model", model)
                    self.status("Gemini is busy, switching model…")
                    self._demote(model, "overloaded")
                    break
                if r.status_code in (401, 403) and "API key" in err["message"]:
                    raise LLMProviderError("Google rejected the Gemini API key. Save a valid key and restart ROVEN.")
                if r.status_code == 404 or (r.status_code == 429 and ("limit: 0" in err["message"] or err["daily"])):
                    log.warning("Gemini model %s unavailable (%s); trying the next one", model, err["message"][:200])
                    with self._lock:                               # no free quota: don't try it again this session
                        if model in self._candidates and len(self._candidates) > 1:
                            self._candidates.remove(model)
                    break                                          # next model
                if r.status_code == 429 or r.status_code >= 500:
                    wait = min(20.0, err["retry"] or 2 ** (attempt + 1))
                    if waited + wait > self.MAX_TOTAL_WAIT:
                        raise LLMProviderError("Gemini is busy right now (free-tier rate limit). Please try again in a minute.")
                    waited += wait
                    log.warning("Gemini rate limit on %s; waiting %.0fs (%s)", model, wait, err["message"][:120])
                    self.status(f"Gemini is busy, retrying in {wait:.0f}s…")
                    self.sleep(wait)
                    continue
                raise LLMProviderError(f"Gemini returned an error: {err['message'][:200]}")
            else:
                continue
        raise LLMProviderError("Gemini's free limit is used up for now (it resets daily around 1 PM Pakistan time), "
                               f"or no model is available. Details: {last_error[:160]}")


def _neutral_signatures(contents: list[dict]) -> list[dict]:
    out = []
    for c in contents:
        parts = []
        for p in c["parts"]:
            p = dict(p)
            if "functionCall" in p:
                p["thoughtSignature"] = "skip_thought_signature_validator"
            else:
                p.pop("thoughtSignature", None)
            parts.append(p)
        out.append({**c, "parts": parts})
    return out


def _error(resp) -> dict:
    try:
        e = resp.json().get("error", {})
    except ValueError:
        e = {}
    message = e.get("message", resp.text[:300])
    retry = 0.0
    daily = False
    for d in e.get("details", []):
        if "retryDelay" in d:
            try:
                retry = float(str(d["retryDelay"]).rstrip("s"))
            except ValueError:
                pass
        for v in d.get("violations", []):
            if "PerDay" in (v.get("quotaId") or "") or "per_day" in (v.get("quotaMetric") or ""):
                daily = True
    return {"message": message, "retry": retry, "daily": daily}
