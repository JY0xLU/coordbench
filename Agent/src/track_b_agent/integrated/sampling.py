from __future__ import annotations

import hashlib
import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from coordbench.cache import load_cached_response, save_cached_response
from coordbench.models import BenchmarkConfig, GenerationRequest
from coordbench.response_validation import response_validation_error
from coordbench.run_state import (
    completed_request_ids,
    request_fallback_identity_from_request,
    request_identity_from_request,
)
from coordbench.runner import _load_panel_items, _provider_instance, _response_record
from coordbench.utils.files import append_jsonl, ensure_dir

from track_b_agent.integrated.progress import PHASE_SAMPLE, log_track_b_line
from track_b_agent.integrated.templates import render_arm_prompts

LOGGER = logging.getLogger(__name__)


def _sample_count_for_round(config: BenchmarkConfig, round_index: int) -> int:
    if int(round_index) == 1:
        return config.sampling.round1_samples
    return config.sampling.round2_samples


def build_track_b_requests(
    config: BenchmarkConfig,
    provider_name: str,
    prepared_dir: Path,
    *,
    repair_round: int,
    sham_round: int,
    repair_template_by_item: dict[str, str],
    item_ids: list[str],
    repair_templates: dict,
) -> tuple[list[GenerationRequest], list[GenerationRequest]]:
    provider_config = config.providers[provider_name]
    panel_items = _load_panel_items(prepared_dir, config.sampling.panel_id, item_ids=item_ids)
    panel_by_id = {str(r["item_id"]): r for _, r in panel_items.iterrows()}

    repair_reqs: list[GenerationRequest] = []
    sham_reqs: list[GenerationRequest] = []
    seed_base = config.sampling.random_seed + repair_round * 1000

    for prompt_language in config.sampling.prompt_languages:
        for item_id in item_ids:
            row = panel_by_id[str(item_id)]
            target_group = str(row.get("target_group", "global"))
            r_template = repair_template_by_item[str(item_id)]
            n_rep = _sample_count_for_round(config, repair_round)
            n_sham = _sample_count_for_round(config, sham_round)

            def _subseed(label: str) -> int:
                h = hashlib.sha256(f"{seed_base}|{item_id}|{prompt_language}|{label}".encode()).hexdigest()
                return seed_base + int(h[:8], 16) % 1_000_000_000

            rng_rep = random.Random(_subseed("repair"))
            rng_sham = random.Random(_subseed("sham"))

            sys_r, usr_r = render_arm_prompts(
                repair_templates,
                r_template,
                prompt_language=prompt_language,
                answer_language=config.sampling.answer_language,
                item_text_en=str(row["item_text_en"]),
                item_text_zh=str(row["item_text_zh"]),
                target_group=target_group,
            )
            sys_s, usr_s = render_arm_prompts(
                repair_templates,
                "R_SHAM",
                prompt_language=prompt_language,
                answer_language=config.sampling.answer_language,
                item_text_en=str(row["item_text_en"]),
                item_text_zh=str(row["item_text_zh"]),
                target_group=target_group,
            )

            for sample_index in range(n_rep):
                repair_reqs.append(
                    GenerationRequest(
                        provider=provider_name,
                        model=provider_config.model,
                        panel_id=str(row["panel_id"]),
                        item_id=str(row["item_id"]),
                        item_text_en=str(row["item_text_en"]),
                        item_text_zh=str(row["item_text_zh"]),
                        prompt_language=prompt_language,
                        answer_language=config.sampling.answer_language,
                        round_index=repair_round,
                        sample_index=sample_index,
                        system_prompt=sys_r,
                        user_prompt=usr_r,
                        temperature=provider_config.temperature,
                        max_output_tokens=provider_config.max_output_tokens,
                        seed=rng_rep.randint(1, 1_000_000_000),
                    )
                )
            for sample_index in range(n_sham):
                sham_reqs.append(
                    GenerationRequest(
                        provider=provider_name,
                        model=provider_config.model,
                        panel_id=str(row["panel_id"]),
                        item_id=str(row["item_id"]),
                        item_text_en=str(row["item_text_en"]),
                        item_text_zh=str(row["item_text_zh"]),
                        prompt_language=prompt_language,
                        answer_language=config.sampling.answer_language,
                        round_index=sham_round,
                        sample_index=sample_index,
                        system_prompt=sys_s,
                        user_prompt=usr_s,
                        temperature=provider_config.temperature,
                        max_output_tokens=provider_config.max_output_tokens,
                        seed=rng_sham.randint(1, 1_000_000_000),
                    )
                )

    return repair_reqs, sham_reqs


def run_track_b_sampling(
    config: BenchmarkConfig,
    run_dir: Path,
    prepared_dir: Path,
    provider_name: str,
    *,
    repair_round: int,
    sham_round: int,
    repair_template_by_item: dict[str, str],
    item_ids: list[str],
    repair_templates: dict,
) -> Path:
    raw_path = run_dir / "raw_generations.jsonl"
    ensure_dir(config.outputs.cache_root)
    completed_ids = completed_request_ids(raw_path)

    provider_config = config.providers[provider_name]
    if not provider_config.enabled:
        raise ValueError(f"Provider `{provider_name}` is not enabled in the benchmark config.")

    provider = _provider_instance(provider_name, config)
    repair_reqs, sham_reqs = build_track_b_requests(
        config,
        provider_name,
        prepared_dir,
        repair_round=repair_round,
        sham_round=sham_round,
        repair_template_by_item=repair_template_by_item,
        item_ids=item_ids,
        repair_templates=repair_templates,
    )
    pending = [
        req
        for req in repair_reqs + sham_reqs
        if request_identity_from_request(req) not in completed_ids
        and request_fallback_identity_from_request(req) not in completed_ids
    ]

    n_pending = len(pending)
    LOGGER.info(
        "Track B sampling: %s pending requests for provider=%s (repair_round=%s sham_round=%s)",
        n_pending,
        provider_name,
        repair_round,
        sham_round,
    )
    if not pending:
        log_track_b_line(
            phase_index=3,
            phase_name=PHASE_SAMPLE,
            step_label="http_requests",
            step_done=1,
            step_total=1,
            detail="all cells already in raw_generations.jsonl (skipped)",
        )
        return run_dir

    log_track_b_line(
        phase_index=3,
        phase_name=PHASE_SAMPLE,
        step_label="http_requests",
        step_done=0,
        step_total=n_pending,
        detail=(
            f"provider={provider_name} concurrency={provider_config.concurrency} "
            f"(lines appear as each request finishes; long gaps = slow API or retries)"
        ),
    )

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
                time.sleep(2)
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

    done_lock = threading.Lock()
    done_count = 0

    with ThreadPoolExecutor(max_workers=provider_config.concurrency) as executor:
        future_map = {executor.submit(execute, request): request for request in pending}
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
            if getattr(response, "error", None) in {None, ""}:
                completed_ids.add(request_identity_from_request(request))
                completed_ids.add(request_fallback_identity_from_request(request))

            with done_lock:
                done_count += 1
                dc = done_count
            log_track_b_line(
                phase_index=3,
                phase_name=PHASE_SAMPLE,
                step_label="http_requests",
                step_done=dc,
                step_total=n_pending,
                detail=(
                    f"item_id={request.item_id} round={request.round_index} "
                    f"lang={request.prompt_language} sample={request.sample_index} "
                    f"source={response_source}"
                ),
            )

    return run_dir

