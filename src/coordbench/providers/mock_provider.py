from __future__ import annotations

import random

from coordbench.models import GenerationRequest, GenerationResponse, ProviderConfig
from coordbench.providers.base import BaseProvider


class MockProvider(BaseProvider):
    def __init__(self, config: ProviderConfig) -> None:
        super().__init__("mock", config)

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        rng = random.Random(request.seed or 0)
        options = ["london", "ronaldo", "everest", "big ben", "angela merkel", "pizza"]
        answer = options[rng.randrange(len(options))]
        return GenerationResponse(
            provider="mock",
            model=request.model,
            text=answer,
            raw_payload={"mock": True, "seed": request.seed},
            finish_reason="mock",
            request_id=f"mock-{request.item_id}-{request.sample_index}",
            prompt_tokens=None,
            completion_tokens=None,
            total_tokens=None,
            latency_seconds=0.0,
        )
