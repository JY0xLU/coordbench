from __future__ import annotations

import os
import time

from google import genai
from google.genai import types

from coordbench.models import GenerationRequest, GenerationResponse, ProviderConfig
from coordbench.providers.base import BaseProvider


class GeminiProvider(BaseProvider):
    def __init__(self, config: ProviderConfig) -> None:
        super().__init__("gemini", config)
        self.client = genai.Client(api_key=os.environ[self.config.api_key_env])

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        started = time.perf_counter()
        response = self.client.models.generate_content(
            model=request.model,
            contents=request.user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=request.system_prompt,
                temperature=request.temperature,
                max_output_tokens=request.max_output_tokens,
            ),
        )
        latency = time.perf_counter() - started
        usage = getattr(response, "usage_metadata", None)
        finish_reason = None
        candidates = getattr(response, "candidates", None)
        if isinstance(candidates, list) and candidates:
            first_candidate = candidates[0]
            finish_reason = getattr(first_candidate, "finish_reason", None)
            if finish_reason is not None:
                finish_reason = str(finish_reason)
        return GenerationResponse(
            provider="gemini",
            model=request.model,
            text=getattr(response, "text", "") or "",
            raw_payload=self._safe_dump(response),
            resolved_model=getattr(response, "model_version", None) or getattr(response, "model", None) or request.model,
            provider_backend="gemini_generate_content",
            finish_reason=finish_reason,
            request_id=getattr(response, "response_id", None),
            prompt_tokens=getattr(usage, "prompt_token_count", None) if usage else None,
            completion_tokens=getattr(usage, "candidates_token_count", None) if usage else None,
            total_tokens=getattr(usage, "total_token_count", None) if usage else None,
            latency_seconds=latency,
        )
