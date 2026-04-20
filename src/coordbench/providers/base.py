from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any

from coordbench.models import GenerationRequest, GenerationResponse, ProviderConfig


class BaseProvider(ABC):
    def __init__(self, provider_name: str, config: ProviderConfig) -> None:
        self.provider_name = provider_name
        self.config = config
        if self.config.enabled and not self.config.model:
            raise ValueError(f"Provider `{provider_name}` is enabled but no model was configured.")
        if self.config.enabled and self.config.api_key_env and not os.environ.get(self.config.api_key_env):
            raise ValueError(
                f"Provider `{provider_name}` is enabled but env var `{self.config.api_key_env}` is not set."
            )

    @abstractmethod
    def generate(self, request: GenerationRequest) -> GenerationResponse:
        raise NotImplementedError

    def _safe_dump(self, payload: Any) -> dict[str, Any]:
        if hasattr(payload, "model_dump"):
            return payload.model_dump()
        if hasattr(payload, "to_dict"):
            return payload.to_dict()
        if isinstance(payload, dict):
            return payload
        return {"repr": repr(payload)}
