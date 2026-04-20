from __future__ import annotations

import json
import os
import time

import requests

from coordbench.models import GenerationRequest, GenerationResponse, ProviderConfig
from coordbench.providers.base import BaseProvider


class OpenAIProvider(BaseProvider):
    def __init__(self, config: ProviderConfig) -> None:
        super().__init__("openai", config)
        self.base_url = str(
            config.extra.get("base_url")
            or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        ).rstrip("/")
        self.timeout_seconds = int(config.timeout_seconds)
        self.session = requests.Session()
        trust_env_raw = str(config.extra.get("trust_env", os.environ.get("OPENAI_TRUST_ENV", "true"))).strip().lower()
        self.session.trust_env = trust_env_raw not in {"0", "false", "no", "off"}

    def _json_response(self, request: GenerationRequest, response: requests.Response, latency: float) -> GenerationResponse:
        payload = response.json()
        choices = payload.get("choices")
        choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
        message = choice.get("message", {}) if isinstance(choice.get("message"), dict) else {}
        content = message.get("content")
        full_text = ""
        if isinstance(content, str):
            full_text = content
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    full_text += str(part.get("text", ""))
        usage = payload.get("usage", {}) if isinstance(payload.get("usage"), dict) else {}
        return GenerationResponse(
            provider="openai",
            model=request.model,
            text=full_text,
            raw_payload=payload,
            resolved_model=str(payload.get("model", "")).strip() or request.model,
            provider_backend="openai_chat_completions_json",
            finish_reason=str(choice.get("finish_reason", "")).strip() or None,
            request_id=str(payload.get("id", "")).strip() or response.headers.get("x-request-id"),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            latency_seconds=latency,
        )

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        started = time.perf_counter()
        payload = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "temperature": request.temperature,
            "max_completion_tokens": request.max_output_tokens,
            "stream": True,
        }
        response = self.session.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {os.environ[self.config.api_key_env]}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream, application/json",
            },
            json=payload,
            stream=True,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        latency = time.perf_counter() - started
        content_type = str(response.headers.get("content-type", "")).lower()
        if "application/json" in content_type:
            return self._json_response(request, response, latency)

        full_text = ""
        response_id = None
        resolved_model = request.model
        finish_reason = None
        usage: dict[str, int | None] = {}
        event_count = 0
        for raw_line in response.iter_lines():
            if not raw_line:
                continue
            line = raw_line.strip()
            if not line.startswith(b"data:"):
                continue
            if line in (b"data: [DONE]", b"data:[DONE]"):
                break
            try:
                chunk = json.loads(line.decode("utf-8", errors="ignore")[5:].strip())
            except Exception:
                continue
            if not isinstance(chunk, dict):
                continue
            event_count += 1
            if isinstance(chunk.get("error"), dict):
                message = str(chunk["error"].get("message", "")).strip() or "provider returned an error payload"
                raise RuntimeError(message)

            response_id = str(chunk.get("id") or response_id or "") or None
            resolved_model = str(chunk.get("model") or resolved_model or "") or request.model
            if isinstance(chunk.get("usage"), dict):
                usage = chunk["usage"]

            choices = chunk.get("choices")
            if not isinstance(choices, list) or not choices:
                continue
            choice = choices[0] if isinstance(choices[0], dict) else {}
            delta = choice.get("delta", {})
            content = delta.get("content")
            if isinstance(content, str):
                full_text += content
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        full_text += str(part.get("text", ""))
            if choice.get("finish_reason") is not None:
                finish_reason = str(choice["finish_reason"])

        if not full_text and event_count == 0:
            try:
                return self._json_response(request, response, latency)
            except Exception:
                pass

        return GenerationResponse(
            provider="openai",
            model=request.model,
            text=full_text,
            raw_payload={
                "stream": True,
                "event_count": event_count,
                "http_status": response.status_code,
                "usage": usage,
            },
            resolved_model=resolved_model,
            provider_backend="openai_chat_completions_stream",
            finish_reason=finish_reason,
            request_id=response_id or response.headers.get("x-request-id"),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            latency_seconds=latency,
        )
