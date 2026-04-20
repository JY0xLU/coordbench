from __future__ import annotations

import os
import time

import httpx
from openai import OpenAI

from coordbench.models import GenerationRequest, GenerationResponse, ProviderConfig
from coordbench.providers.base import BaseProvider


class DeepSeekProvider(BaseProvider):
    def __init__(self, config: ProviderConfig) -> None:
        super().__init__("deepseek", config)
        base_url = str(config.extra.get("base_url", "https://api.deepseek.com")).rstrip("/")
        read_s = max(30.0, float(self.config.timeout_seconds))
        timeout = httpx.Timeout(connect=30.0, read=read_s, write=read_s, pool=30.0)
        # Must read YAML `trust_env` / DEEPSEEK_TRUST_ENV: default http_proxy often points at a dead proxy.
        trust_env_raw = str(
            config.extra.get("trust_env", os.environ.get("DEEPSEEK_TRUST_ENV", "true"))
        ).strip().lower()
        trust_env = trust_env_raw not in {"0", "false", "no", "off"}
        self._http_client = httpx.Client(timeout=timeout, trust_env=trust_env)
        self.client = OpenAI(
            api_key=os.environ[self.config.api_key_env],
            base_url=base_url,
            http_client=self._http_client,
            max_retries=2,
        )

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        started = time.perf_counter()
        response = self.client.chat.completions.create(
            model=request.model,
            messages=[
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            temperature=request.temperature,
            max_tokens=request.max_output_tokens,
            stream=False,
        )
        latency = time.perf_counter() - started
        usage = getattr(response, "usage", None)
        choice = response.choices[0] if getattr(response, "choices", None) else None
        text = choice.message.content if choice and choice.message else ""
        finish_reason = choice.finish_reason if choice else None
        return GenerationResponse(
            provider="deepseek",
            model=request.model,
            text=text or "",
            raw_payload=self._safe_dump(response),
            resolved_model=getattr(response, "model", None) or request.model,
            provider_backend="deepseek_openai_compat",
            finish_reason=finish_reason,
            request_id=getattr(response, "id", None),
            prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
            completion_tokens=getattr(usage, "completion_tokens", None) if usage else None,
            total_tokens=getattr(usage, "total_tokens", None) if usage else None,
            latency_seconds=latency,
        )
