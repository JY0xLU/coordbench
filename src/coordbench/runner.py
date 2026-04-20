from __future__ import annotations

import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from coordbench.cache import cache_key_for_request, load_cached_response, save_cached_response
from coordbench.config import load_config
from coordbench.models import BenchmarkConfig, GenerationRequest
from coordbench.prompts import build_prompt_messages
from coordbench.response_validation import response_validation_error
from coordbench.run_state import (
    completed_request_ids,
    load_run_manifest,
    latest_prepared_snapshot_or_raise,
    prepared_snapshot_dir_for_manifest,
    request_fallback_identity_from_request,
    request_identity_from_request,
)
from coordbench.utils.files import append_jsonl, ensure_dir, read_json, write_json

LOGGER = logging.getLogger(__name__)
UTC = getattr(__import__("datetime"), "UTC", timezone.utc)


def _provider_instance(provider_name: str, config: BenchmarkConfig):
    provider_config = config.providers[provider_name]
    if provider_name == "anthropic":
        from coordbench.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(provider_config)
    if provider_name == "openai":
        from coordbench.providers.openai_provider import OpenAIProvider

        return OpenAIProvider(provider_config)
    if provider_name == "gemini":
        from coordbench.providers.gemini_provider import GeminiProvider

        return GeminiProvider(provider_config)
    if provider_name == "deepseek":
        from coordbench.providers.deepseek_provider import DeepSeekProvider

        return DeepSeekProvider(provider_config)
    if provider_name == "mock":
        from coordbench.providers.mock_provider import MockProvider

        return MockProvider(provider_config)
    raise KeyError(f"Unknown provider: {provider_name}")


def _write_run_manifest(run_dir: Path, config: BenchmarkConfig, prepared_dir: Path, *, run_id: str | None = None) -> None:
    manifest = {
        "run_id": run_id or run_dir.name,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "config_path": str(config.config_path),
        "prepared_snapshot_id": prepared_dir.name,
        "prepared_snapshot_path": str(prepared_dir.resolve()),
        "panel_id": config.sampling.panel_id,
        "prompt_languages": config.sampling.prompt_languages,
        "answer_language": config.sampling.answer_language,
        "configured_item_ids": config.sampling.item_ids or [],
    }
    write_json(run_dir / "run_manifest.json", manifest)


def create_run_dir(config: BenchmarkConfig, prepared_dir: Path) -> Path:
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = ensure_dir(config.outputs.run_root / run_id)
    _write_run_manifest(run_dir, config, prepared_dir, run_id=run_id)
    return run_dir


def _load_panel_items(prepared_dir: Path, panel_id: str, item_ids: list[str] | None = None) -> pd.DataFrame:
    frame = pd.read_csv(prepared_dir / "panel_items.csv")
    panel = frame[frame["panel_id"] == panel_id].copy()
    if item_ids:
        panel = panel[panel["item_id"].isin(item_ids)].copy()
    if panel.empty:
        raise ValueError(f"No items found for panel `{panel_id}`.")
    return panel.sort_values("item_number").reset_index(drop=True)


def _request_records(
    config: BenchmarkConfig,
    provider_name: str,
    panel_items: pd.DataFrame,
    round_index: int,
    item_ids: list[str] | None = None,
) -> list[GenerationRequest]:
    provider_config = config.providers[provider_name]
    requests: list[GenerationRequest] = []
    sample_count = (
        config.sampling.round1_samples if round_index == 1 else config.sampling.round2_samples
    )
    seed_rng = random.Random(config.sampling.random_seed + round_index)
    for prompt_language in config.sampling.prompt_languages:
        for _, item in panel_items.iterrows():
            if item_ids and item["item_id"] not in item_ids:
                continue
            messages = build_prompt_messages(
                item_text_en=item["item_text_en"],
                item_text_zh=item["item_text_zh"],
                prompt_language=prompt_language,
                answer_language=config.sampling.answer_language,
                round_index=round_index,
                target_group=item.get("target_group", "global"),
            )
            for sample_index in range(sample_count):
                requests.append(
                    GenerationRequest(
                        provider=provider_name,
                        model=provider_config.model,
                        panel_id=item["panel_id"],
                        item_id=item["item_id"],
                        item_text_en=item["item_text_en"],
                        item_text_zh=item["item_text_zh"],
                        prompt_language=prompt_language,
                        answer_language=config.sampling.answer_language,
                        round_index=round_index,
                        sample_index=sample_index,
                        system_prompt=messages[0].content,
                        user_prompt=messages[1].content,
                        temperature=provider_config.temperature,
                        max_output_tokens=provider_config.max_output_tokens,
                        seed=seed_rng.randint(1, 1_000_000_000),
                    )
                )
    return requests


def _provider_cached_tokens(response: Any) -> int | None:
    payload = getattr(response, "raw_payload", {})
    if not isinstance(payload, dict):
        return None
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    prompt_details = usage.get("prompt_tokens_details")
    if isinstance(prompt_details, dict) and prompt_details.get("cached_tokens") is not None:
        return int(prompt_details["cached_tokens"])
    return None


def _response_record(
    request: GenerationRequest,
    response: Any,
    *,
    provider_timeout_seconds: int,
    provider_concurrency: int,
    retry_count: int,
    attempt_count: int,
    response_source: str,
) -> dict[str, Any]:
    return {
        "provider": request.provider,
        "model": request.model,
        "requested_model": request.model,
        "resolved_model": getattr(response, "resolved_model", None) or request.model,
        "provider_backend": getattr(response, "provider_backend", None) or request.provider,
        "panel_id": request.panel_id,
        "item_id": request.item_id,
        "item_text_en": request.item_text_en,
        "item_text_zh": request.item_text_zh,
        "prompt_language": request.prompt_language,
        "answer_language": request.answer_language,
        "round_index": request.round_index,
        "sample_index": request.sample_index,
        "temperature": request.temperature,
        "max_output_tokens": request.max_output_tokens,
        "seed": request.seed,
        "provider_timeout_seconds": provider_timeout_seconds,
        "provider_concurrency": provider_concurrency,
        "request_cache_key": cache_key_for_request(request),
        "system_prompt": request.system_prompt,
        "user_prompt": request.user_prompt,
        "response_text": response.text,
        "finish_reason": response.finish_reason,
        "request_id": response.request_id,
        "prompt_tokens": response.prompt_tokens,
        "completion_tokens": response.completion_tokens,
        "total_tokens": response.total_tokens,
        "latency_seconds": response.latency_seconds,
        "response_source": response_source,
        "retry_count": retry_count,
        "attempt_count": attempt_count,
        "cache_hit": response.cache_hit,
        "disk_cache_hit": response.cache_hit,
        "provider_cached_tokens": _provider_cached_tokens(response),
        "error": response.error,
        "raw_payload": response.raw_payload,
        "generated_at_utc": datetime.now(UTC).isoformat(),
    }


def run_sampling(
    config_path: str | Path,
    *,
    run_dir: Path | None = None,
    round_index: int = 1,
    item_ids: list[str] | None = None,
) -> Path:
    config = load_config(config_path)
    enabled_providers = [name for name, provider in config.providers.items() if provider.enabled]
    if config.sampling.max_enabled_providers > 0 and len(enabled_providers) > config.sampling.max_enabled_providers:
        raise ValueError(
            "Too many enabled providers for one run: "
            f"{enabled_providers}. Set sampling.max_enabled_providers or disable extra providers."
        )
    if run_dir is None:
        prepared_dir = latest_prepared_snapshot_or_raise()
        run_dir = create_run_dir(config, prepared_dir)
    else:
        run_dir = Path(run_dir)
        ensure_dir(run_dir)
        manifest_path = run_dir / "run_manifest.json"
        if manifest_path.exists():
            manifest = load_run_manifest(run_dir)
            prepared_dir = prepared_snapshot_dir_for_manifest(manifest)
            if str(manifest.get("panel_id", "")) != config.sampling.panel_id:
                raise ValueError(
                    "Existing run directory is bound to a different panel_id; use a new run directory or matching config."
                )
        else:
            prepared_dir = latest_prepared_snapshot_or_raise()
            _write_run_manifest(run_dir, config, prepared_dir, run_id=run_dir.name)

    requested_item_ids = item_ids
    if requested_item_ids is None and round_index == 1:
        requested_item_ids = config.sampling.item_ids

    panel_items = _load_panel_items(prepared_dir, config.sampling.panel_id, item_ids=requested_item_ids)
    raw_path = run_dir / "raw_generations.jsonl"
    ensure_dir(config.outputs.cache_root)
    completed_ids = completed_request_ids(raw_path)

    for provider_name, provider_config in config.providers.items():
        if not provider_config.enabled:
            continue
        provider = _provider_instance(provider_name, config)
        requests = _request_records(config, provider_name, panel_items, round_index, item_ids=requested_item_ids)
        pending_requests = [
            request
            for request in requests
            if request_identity_from_request(request) not in completed_ids
            and request_fallback_identity_from_request(request) not in completed_ids
        ]
        LOGGER.info(
            "Running %s pending requests for provider=%s round=%s (%s already complete)",
            len(pending_requests),
            provider_name,
            round_index,
            len(requests) - len(pending_requests),
        )
        if not pending_requests:
            continue

        def execute(single_request: GenerationRequest):
            cached = load_cached_response(config.outputs.cache_root, single_request)
            if cached:
                return {
                    "request": single_request,
                    "response": cached,
                    "retry_count": 0,
                    "attempt_count": 0,
                    "response_source": "disk_cache",
                }

            last_error: Exception | None = None
            for attempt in range(provider_config.max_retries):
                try:
                    response = provider.generate(single_request)
                    validation_error = response_validation_error(
                        text=response.text,
                        finish_reason=response.finish_reason,
                        error=response.error,
                    )
                    if validation_error:
                        raise RuntimeError(validation_error)
                    save_cached_response(config.outputs.cache_root, single_request, response)
                    time.sleep(2)  # cooldown between successful requests
                    return {
                        "request": single_request,
                        "response": response,
                        "retry_count": attempt,
                        "attempt_count": attempt + 1,
                        "response_source": "provider_api",
                    }
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    sleep_seconds = min(2**attempt * 3, 60)
                    LOGGER.warning(
                        "Provider %s failed on %s attempt %s/%s: %s",
                        provider_name,
                        single_request.item_id,
                        attempt + 1,
                        provider_config.max_retries,
                        exc,
                    )
                    time.sleep(sleep_seconds)
            raise RuntimeError(str(last_error) if last_error else "unknown provider error")

        with ThreadPoolExecutor(max_workers=provider_config.concurrency) as executor:
            future_map = {executor.submit(execute, request): request for request in pending_requests}
            for future in as_completed(future_map):
                request = future_map[future]
                try:
                    result = future.result()
                    response = result["response"]
                    retry_count = int(result["retry_count"])
                    attempt_count = int(result["attempt_count"])
                    response_source = str(result["response_source"])
                except Exception as exc:  # noqa: BLE001
                    response = type(
                        "ErrorResponse",
                        (),
                        {
                            "text": "",
                            "resolved_model": request.model,
                            "provider_backend": provider_name,
                            "finish_reason": None,
                            "request_id": None,
                            "prompt_tokens": None,
                            "completion_tokens": None,
                            "total_tokens": None,
                            "latency_seconds": None,
                            "cache_hit": False,
                            "error": str(exc),
                            "raw_payload": {"error": str(exc)},
                        },
                    )()
                    retry_count = provider_config.max_retries
                    attempt_count = provider_config.max_retries
                    response_source = "provider_error"
                append_jsonl(
                    raw_path,
                    _response_record(
                        request,
                        response,
                        provider_timeout_seconds=provider_config.timeout_seconds,
                        provider_concurrency=provider_config.concurrency,
                        retry_count=retry_count,
                        attempt_count=attempt_count,
                        response_source=response_source,
                    ),
                )
                if response.error in {None, ""}:
                    completed_ids.add(request_identity_from_request(request))
                    completed_ids.add(request_fallback_identity_from_request(request))

    manifest_path = run_dir / "run_manifest.json"
    manifest = read_json(manifest_path)
    manifest.setdefault("completed_rounds", [])
    if round_index not in manifest["completed_rounds"]:
        manifest["completed_rounds"].append(round_index)
    write_json(manifest_path, manifest)
    return run_dir
