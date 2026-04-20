from __future__ import annotations

import os
import time

import requests

from coordbench.models import GenerationRequest, GenerationResponse, ProviderConfig
from coordbench.providers.base import BaseProvider


class AnthropicProvider(BaseProvider):
    def __init__(self, config: ProviderConfig) -> None:
        super().__init__("anthropic", config)
        self.api_key = os.environ[self.config.api_key_env]
        self.base_url = str(
            config.extra.get("base_url")
            or os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
        ).rstrip("/")
        self.api_version = str(config.extra.get("anthropic_version", "2023-06-01"))
        self.compat_mode = str(config.extra.get("compat_mode", "anthropic")).lower()
        self.timeout_seconds = int(config.timeout_seconds)
        self.session = requests.Session()
        self.session.trust_env = False

    def _messages_url(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/messages"
        return f"{self.base_url}/v1/messages"

    @staticmethod
    def _json_payload(response: requests.Response) -> dict:
        headers = getattr(response, "headers", {}) or {}
        content_type = (headers.get("content-type") or "").lower()
        if "text/event-stream" not in content_type:
            return response.json()

        chunks: list[str] = []
        for raw_line in response.text.splitlines():
            line = raw_line.strip()
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            chunks.append(data)
        if not chunks:
            raise ValueError("Empty event-stream response body.")
        return requests.models.complexjson.loads(chunks[-1])

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        if self.compat_mode == "openai":
            return self._generate_openai_compat(request)
        return self._generate_anthropic(request)

    def _generate_anthropic(self, request: GenerationRequest) -> GenerationResponse:
        started = time.perf_counter()
        response = self.session.post(
            self._messages_url(),
            timeout=self.timeout_seconds,
            headers={
                "x-api-key": self.api_key,
                "Authorization": f"Bearer {self.api_key}",
                "anthropic-version": self.api_version,
                "content-type": "application/json",
                "accept": "application/json",
            },
            json={
                "model": request.model,
                "system": request.system_prompt,
                "messages": [{"role": "user", "content": request.user_prompt}],
                "max_tokens": request.max_output_tokens,
                "temperature": request.temperature,
            },
        )
        response.raise_for_status()
        payload = self._json_payload(response)
        latency = time.perf_counter() - started
        content = payload.get("content", [])
        if isinstance(content, str):
            text = content.strip()
        elif isinstance(payload.get("choices"), list) and payload["choices"]:
            choice = payload["choices"][0]
            message = choice.get("message") if isinstance(choice, dict) else None
            text = str((message or {}).get("content", "")).strip()
        else:
            text_blocks = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            text = "".join(text_blocks).strip()
        usage = payload.get("usage", {}) if isinstance(payload, dict) else {}
        input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
        output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
        total_tokens = None
        if input_tokens is not None or output_tokens is not None:
            total_tokens = usage.get("total_tokens", (input_tokens or 0) + (output_tokens or 0))
        return GenerationResponse(
            provider="anthropic",
            model=request.model,
            text=text,
            raw_payload=payload,
            resolved_model=str(payload.get("model", "")) or request.model,
            provider_backend="anthropic_messages",
            finish_reason=payload.get("stop_reason")
            or (
                payload["choices"][0].get("finish_reason")
                if isinstance(payload.get("choices"), list) and payload["choices"]
                else None
            ),
            request_id=str(payload.get("id", "")) or None,
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_seconds=latency,
        )

    def _generate_openai_compat(self, request: GenerationRequest) -> GenerationResponse:
        started = time.perf_counter()
        response = self.session.post(
            f"{self.base_url}/v1/chat/completions",
            timeout=self.timeout_seconds,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "content-type": "application/json",
                "accept": "application/json",
            },
            json={
                "model": request.model,
                "messages": [
                    {"role": "system", "content": request.system_prompt},
                    {"role": "user", "content": request.user_prompt},
                ],
                "max_tokens": request.max_output_tokens,
                "temperature": request.temperature,
            },
        )
        response.raise_for_status()
        payload = self._json_payload(response)
        latency = time.perf_counter() - started
        choices = payload.get("choices", [])
        message = choices[0].get("message", {}) if choices else {}
        usage = payload.get("usage", {}) if isinstance(payload, dict) else {}
        return GenerationResponse(
            provider="anthropic",
            model=request.model,
            text=str(message.get("content", "")).strip(),
            raw_payload=payload,
            resolved_model=str(payload.get("model", "")) or request.model,
            provider_backend="anthropic_openai_compat",
            finish_reason=choices[0].get("finish_reason") if choices else None,
            request_id=str(payload.get("id", "")) or None,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            latency_seconds=latency,
        )
