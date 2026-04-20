from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class Message:
    role: str
    content: str


@dataclass(slots=True)
class GenerationRequest:
    provider: str
    model: str
    panel_id: str
    item_id: str
    item_text_en: str
    item_text_zh: str
    prompt_language: str
    answer_language: str
    round_index: int
    sample_index: int
    system_prompt: str
    user_prompt: str
    temperature: float
    max_output_tokens: int
    seed: int | None = None

    def to_cache_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class GenerationResponse:
    provider: str
    model: str
    text: str
    raw_payload: dict[str, Any]
    resolved_model: str | None = None
    provider_backend: str | None = None
    finish_reason: str | None = None
    request_id: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    latency_seconds: float | None = None
    cache_hit: bool = False
    error: str | None = None


@dataclass(slots=True)
class SourceAsset:
    category: str
    name: str
    url: str


@dataclass(slots=True)
class ProviderConfig:
    enabled: bool
    model: str
    api_key_env: str
    max_retries: int = 5
    concurrency: int = 3
    temperature: float = 1.0
    max_output_tokens: int = 32
    timeout_seconds: int = 120
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SamplingConfig:
    panel_id: str
    answer_language: str
    prompt_languages: list[str]
    item_ids: list[str] | None
    max_enabled_providers: int
    round1_samples: int
    round2_samples: int
    enable_round2: bool
    round2_trigger: str
    random_seed: int


@dataclass(slots=True)
class NormalizationConfig:
    alias_path: Path
    allow_unmapped: bool
    fuzzy_match_threshold: int


@dataclass(slots=True)
class AnalysisConfig:
    bootstrap_resamples: int
    item_bootstrap_resamples: int
    min_cell_completion_rate: float = 0.8


@dataclass(slots=True)
class OutputConfig:
    run_root: Path
    cache_root: Path


@dataclass(slots=True)
class BenchmarkConfig:
    config_path: Path
    providers: dict[str, ProviderConfig]
    sampling: SamplingConfig
    normalization: NormalizationConfig
    analysis: AnalysisConfig
    outputs: OutputConfig
