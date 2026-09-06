"""Custom API provider — generate-only adapter for OpenAI/Anthropic-compatible endpoints.

Endpoint is the FULL final URL (no path auto-appending). Uses stdlib urllib —
no extra dependency. api_key is never logged; server error text is sanitized.
"""

import hashlib
import json
import socket
import time
import urllib.error
import urllib.request
from typing import Optional

from adapters.base import BaseAdapter
from conversation.models import ConversationModel, Message


class CustomAPIError(RuntimeError):
    def __init__(self, message, http_status=None):
        super().__init__(message)
        self.http_status = http_status


class CustomAdapter(BaseAdapter):
    """HTTP API provider. generate(prompt) -> ConversationModel. No browser needed."""

    name = "custom"

    def __init__(self, slot, config, log_func=None, cancel_check=None):
        self.slot = slot
        self.config = dict(config or {})
        self.log = log_func or (lambda msg: None)
        self.cancel_check = cancel_check or (lambda: None)

    # ── BaseAdapter (browser flow) — not used for custom ──

    def healthcheck(self):
        return bool(str(self.config.get("endpoint", "")).strip())

    def list_chats(self):
        return []

    def open_chat(self, chat):
        return True

    def extract_chat(self, chat):
        return None

    # ── Config accessors ──

    @property
    def endpoint(self):
        return str(self.config.get("endpoint", "")).strip()

    @property
    def model(self):
        return str(self.config.get("model", "")).strip()

    @property
    def protocol(self):
        p = str(self.config.get("protocol", "openai")).strip().lower()
        return p if p in ("openai", "anthropic") else "openai"

    @property
    def timeout(self):
        try:
            return max(5, min(300, int(self.config.get("timeout", 30))))
        except (TypeError, ValueError):
            return 30

    # ── Generation (primary method) ──

    def generate(self, prompt) -> Optional[ConversationModel]:
        prompt = str(prompt or "").strip()
        if not prompt:
            raise CustomAPIError("Пустой промпт")
        self._validate_config()
        self.log(f"[CUSTOM{self.slot}] POST {self.endpoint} model={self.model}")
        body = self._build_body(
            self.protocol, self.model, str(self.config.get("system_prompt", "") or ""), prompt
        )
        headers = self._build_headers(self.protocol, str(self.config.get("api_key", "") or ""))
        data = self._post(self.endpoint, body, headers)
        text = self._parse_response(self.protocol, data)
        if not text or not text.strip():
            raise CustomAPIError("API вернул ответ без содержимого assistant-сообщения")
        self.log(f"[CUSTOM{self.slot}] OK: {len(text)} chars")
        return self._to_model(prompt, text)

    def test_connection(self):
        """Safe test: minimal request, no user data. Returns dict, never raises."""
        try:
            if not self.endpoint:
                return {"ok": False, "error": "Endpoint не указан"}
            if not self.model:
                return {"ok": False, "error": "Model не указана"}
            body = self._build_body(self.protocol, self.model, "", "Reply with: OK")
            headers = self._build_headers(self.protocol, str(self.config.get("api_key", "") or ""))
            data = self._post(self.endpoint, body, headers)
            text = self._parse_response(self.protocol, data)
            if not text or not text.strip():
                return {"ok": False, "error": "Ответ не содержит assistant-сообщения", "http_status": 200}
            return {"ok": True, "model": self.model, "response": text[:200], "http_status": 200}
        except CustomAPIError as e:
            out = {"ok": False, "error": str(e)}
            if e.http_status is not None:
                out["http_status"] = e.http_status
            return out
        except Exception as e:
            return {"ok": False, "error": self._sanitize(str(e))}

    # ── Internals ──

    def _validate_config(self):
        if not self.endpoint:
            raise CustomAPIError("Endpoint не указан")
        if not self.model:
            raise CustomAPIError("Model не указана")

    def _post(self, url, body, headers):
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise CustomAPIError(self._fmt_http_error(e.code, detail), http_status=e.code)
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            raise CustomAPIError(f"Ошибка соединения: {self._sanitize(str(reason))}")
        except socket.timeout:
            raise CustomAPIError(f"Timeout ({self.timeout}s)")
        except TimeoutError:
            raise CustomAPIError(f"Timeout ({self.timeout}s)")
        try:
            return json.loads(raw)
        except ValueError:
            raise CustomAPIError("Сервер вернул не-JSON ответ: " + self._sanitize(raw[:200]))

    def _fmt_http_error(self, code, detail):
        msg = detail[:300] if detail else ""
        try:
            data = json.loads(detail)
            err = data.get("error", data)
            if isinstance(err, dict):
                msg = str(err.get("message", err.get("type", msg)))
            else:
                msg = str(err)
        except Exception:
            pass
        return f"HTTP {code}: {self._sanitize(msg)}"

    def _sanitize(self, text):
        key = str(self.config.get("api_key", "") or "")
        if key and key in text:
            text = text.replace(key, "***")
        return text

    @staticmethod
    def _build_body(protocol, model, system_prompt, user_prompt):
        if protocol == "anthropic":
            body = {
                "model": model,
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": user_prompt}],
            }
            if system_prompt.strip():
                body["system"] = system_prompt.strip()
            return body
        messages = []
        if system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt.strip()})
        messages.append({"role": "user", "content": user_prompt})
        return {"model": model, "messages": messages}

    @staticmethod
    def _build_headers(protocol, api_key):
        headers = {"Content-Type": "application/json"}
        if api_key:
            if protocol == "anthropic":
                headers["x-api-key"] = api_key
                headers["anthropic-version"] = "2023-06-01"
            else:
                headers["Authorization"] = f"Bearer {api_key}"
        return headers

    @staticmethod
    def _parse_response(protocol, data):
        try:
            if protocol == "anthropic":
                content = data.get("content") or []
                if isinstance(content, list):
                    parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            parts.append(str(block.get("text", "")))
                        elif isinstance(block, str):
                            parts.append(block)
                    return "\n".join(p for p in parts if p).strip()
                return ""
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            return str(message.get("content", "") or "").strip()
        except (AttributeError, IndexError, TypeError):
            return ""

    def _to_model(self, prompt, assistant_text):
        ts = time.time()
        # system_prompt is a request parameter, not conversation content —
        # only user + assistant go into the model (writer renders non-user as "AI").
        messages = [
            Message(role="user", content=prompt, timestamp=ts),
            Message(role="assistant", content=assistant_text, timestamp=ts),
        ]
        seed = f"custom{self.slot}|{self.model}|{prompt}|{ts}"
        stable_id = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
        title = " ".join(prompt.split())[:60] or "Custom chat"
        return ConversationModel(
            source=f"custom{self.slot}",
            stable_id=stable_id,
            title=title,
            source_url=self.endpoint,
            messages=messages,
            tree=None,
            metadata={"model": self.model, "protocol": self.protocol, "slot": self.slot},
        )
