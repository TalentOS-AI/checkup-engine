"""Minimal OpenAI-compatible chat client (stdlib only) + a deterministic offline stand-in."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "https://llm.agentbay.asia/v1"
DEFAULT_MODEL = "deepseek-v4"


class LLMError(RuntimeError):
    pass


class OpenAICompatClient:
    """Calls ``{base}/chat/completions``. The key comes from the environment, never from code."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None,
                 timeout: float = 90.0):
        self.base_url = (base_url or os.environ.get("GATEWAY_CHECKUP_BASE_URL")
                       or os.environ.get("CHECKUP_LLM_BASE") or DEFAULT_BASE).rstrip("/")
        self.api_key = api_key or os.environ.get("GATEWAY_CHECKUP_KEY") or ""
        self.model = (model or os.environ.get("GATEWAY_CHECKUP_MODEL")
                      or os.environ.get("CHECKUP_LLM_MODEL") or DEFAULT_MODEL)
        self.timeout = timeout
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0, "cost_usd": 0.0}
        if not self.api_key:
            raise LLMError("GATEWAY_CHECKUP_KEY is not set")

    def chat_json(self, prompt: str, max_tokens: int = 2500) -> dict:
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        last = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    cost = resp.headers.get("x-litellm-response-cost")
                break
            except urllib.error.HTTPError as exc:
                last = f"http {exc.code}"
                if exc.code not in (429, 500, 502, 503, 504):
                    raise LLMError(last) from exc
            except (urllib.error.URLError, OSError, ValueError) as exc:
                last = str(exc)
            time.sleep(2 * (attempt + 1))
        else:
            raise LLMError(f"LLM call failed: {last}")
        u = data.get("usage") or {}
        self.usage["prompt_tokens"] += int(u.get("prompt_tokens") or 0)
        self.usage["completion_tokens"] += int(u.get("completion_tokens") or 0)
        self.usage["calls"] += 1
        try:
            self.usage["cost_usd"] += float(cost) if cost else 0.0
        except ValueError:
            pass
        content = data["choices"][0]["message"].get("content") or "{}"
        return parse_json_loose(content)


def parse_json_loose(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise LLMError("model did not return JSON")
    try:
        return json.loads(text[start:end + 1])
    except ValueError as exc:
        raise LLMError("model returned invalid JSON") from exc


class MockLLM:
    """Test double: returns canned responses in order, records prompts."""

    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.prompts: list[str] = []
        self.model = "mock"
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0, "cost_usd": 0.0}

    def chat_json(self, prompt: str, max_tokens: int = 2500) -> dict:
        self.prompts.append(prompt)
        self.usage["calls"] += 1
        if not self.responses:
            raise LLMError("no more mock responses")
        return self.responses.pop(0)
