from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from coordbench.models import (
    AnalysisConfig,
    BenchmarkConfig,
    NormalizationConfig,
    OutputConfig,
    ProviderConfig,
    SamplingConfig,
)
from coordbench.paths import aliases_path, artifacts_root

ENV_PATTERN = re.compile(r"^\$\{([A-Z0-9_]+)(?::([^}]*))?\}$")


def _expand_env(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if isinstance(value, str):
        match = ENV_PATTERN.match(value)
        if match:
            env_name, default = match.groups()
            return os.environ.get(env_name, default or "")
        return value
    return value


def _resolve_path(config_dir: Path, value: str | None, fallback: Path) -> Path:
    if not value:
        return fallback
    path = Path(value)
    if path.is_absolute():
        return path
    return (config_dir / path).resolve()


def load_config(path: str | Path) -> BenchmarkConfig:
    load_dotenv()
    config_path = Path(path).resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    raw = _expand_env(raw)
    config_dir = config_path.parent

    provider_configs: dict[str, ProviderConfig] = {}
    for provider_name, provider_raw in (raw.get("providers") or {}).items():
        provider_configs[provider_name] = ProviderConfig(
            enabled=bool(provider_raw.get("enabled", False)),
            model=str(provider_raw.get("model", "")).strip(),
            api_key_env=str(provider_raw.get("api_key_env", "")),
            max_retries=int(provider_raw.get("max_retries", 5)),
            concurrency=int(provider_raw.get("concurrency", 3)),
            temperature=float(provider_raw.get("temperature", 1.0)),
            max_output_tokens=int(provider_raw.get("max_output_tokens", 32)),
            timeout_seconds=int(provider_raw.get("timeout_seconds", 120)),
            extra={
                k: v
                for k, v in provider_raw.items()
                if k
                not in {
                    "enabled",
                    "model",
                    "api_key_env",
                    "max_retries",
                    "concurrency",
                    "temperature",
                    "max_output_tokens",
                    "timeout_seconds",
                }
            },
        )

    sampling_raw = raw.get("sampling") or {}
    normalization_raw = raw.get("normalization") or {}
    analysis_raw = raw.get("analysis") or {}
    outputs_raw = raw.get("outputs") or {}

    return BenchmarkConfig(
        config_path=config_path,
        providers=provider_configs,
        sampling=SamplingConfig(
            panel_id=str(sampling_raw.get("panel_id", "study2_british_within")),
            answer_language=str(sampling_raw.get("answer_language", "English")),
            prompt_languages=list(sampling_raw.get("prompt_languages", ["en", "zh"])),
            item_ids=list(sampling_raw.get("item_ids", [])) or None,
            max_enabled_providers=int(sampling_raw.get("max_enabled_providers", 1)),
            round1_samples=int(sampling_raw.get("round1_samples", 30)),
            round2_samples=int(sampling_raw.get("round2_samples", 10)),
            enable_round2=bool(sampling_raw.get("enable_round2", True)),
            round2_trigger=str(sampling_raw.get("round2_trigger", "cross_lingual_top1_mismatch")),
            random_seed=int(sampling_raw.get("random_seed", 20260324)),
        ),
        normalization=NormalizationConfig(
            alias_path=_resolve_path(
                config_dir,
                normalization_raw.get("alias_path"),
                aliases_path(),
            ),
            allow_unmapped=bool(normalization_raw.get("allow_unmapped", False)),
            fuzzy_match_threshold=int(normalization_raw.get("fuzzy_match_threshold", 95)),
        ),
        analysis=AnalysisConfig(
            bootstrap_resamples=int(analysis_raw.get("bootstrap_resamples", 1000)),
            item_bootstrap_resamples=int(analysis_raw.get("item_bootstrap_resamples", 1000)),
            min_cell_completion_rate=float(analysis_raw.get("min_cell_completion_rate", 0.8)),
        ),
        outputs=OutputConfig(
            run_root=_resolve_path(
                config_dir,
                outputs_raw.get("run_root"),
                artifacts_root() / "runs",
            ),
            cache_root=_resolve_path(
                config_dir,
                outputs_raw.get("cache_root"),
                artifacts_root() / "cache",
            ),
        ),
    )
