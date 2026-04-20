from __future__ import annotations

import json
import logging
import re
from typing import Any

from coordbench.models import BenchmarkConfig, GenerationRequest
from coordbench.runner import _provider_instance

from track_b_agent.integrated.progress import PHASE_DIAGNOSE, log_track_b_line

LOGGER = logging.getLogger(__name__)

VALID_TAGS = frozenset(
    {"T_TRANS", "T_SALIENCE", "T_CULT", "T_LEAK", "T_LEX", "T_FRAG", "T_LITERAL", "T_UNK"}
)


def _diagnosis_system_prompt() -> str:
    return (
        "You classify failure modes for cross-lingual coordination benchmarks. "
        "Reply with a single JSON object only, no markdown. "
        f'Schema: {{"primary_tag": one of {sorted(VALID_TAGS)}, "rationale": string}}.'
    )


def _diagnosis_user_prompt(item_record: dict[str, Any]) -> str:
    snap = item_record.get("metrics_snapshot") or {}
    return (
        "Classify the primary failure tag for this flagged item using its round-1 metrics snapshot.\n"
        f"{json.dumps(snap, ensure_ascii=False, indent=2)}"
    )


def _parse_tag_from_text(text: str) -> str:
    text = text.strip()
    if not text:
        return "T_UNK"
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        obj = json.loads(text[start:end])
        tag = str(obj.get("primary_tag", "T_UNK")).strip().upper()
        if tag in VALID_TAGS:
            return tag
    except (ValueError, json.JSONDecodeError):
        pass
    for tag in sorted(VALID_TAGS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(tag)}\b", text, flags=re.IGNORECASE):
            return tag
    return "T_UNK"


def diagnose_flagged_items(
    config: BenchmarkConfig,
    provider_name: str,
    flagged_records: list[dict[str, Any]],
    *,
    max_output_tokens: int = 256,
) -> list[dict[str, Any]]:
    """Call the enabled LLM once per flagged item; return rows with item_id and primary_tag."""
    provider = _provider_instance(provider_name, config)
    provider_config = config.providers[provider_name]
    model = provider_config.model
    results: list[dict[str, Any]] = []
    n_flag = len(flagged_records)
    if n_flag == 0:
        log_track_b_line(
            phase_index=2,
            phase_name=PHASE_DIAGNOSE,
            step_label="api_calls",
            step_done=1,
            step_total=1,
            detail="no flagged items (skipped)",
        )
        return results
    for idx, rec in enumerate(flagged_records, start=1):
        item_id = str(rec["item_id"])
        log_track_b_line(
            phase_index=2,
            phase_name=PHASE_DIAGNOSE,
            step_label="api_calls",
            step_done=idx - 1,
            step_total=n_flag,
            detail=f"calling LLM for item_id={item_id} (waits until response or timeout)",
        )
        req = GenerationRequest(
            provider=provider_name,
            model=model,
            panel_id=config.sampling.panel_id,
            item_id=item_id,
            item_text_en="",
            item_text_zh="",
            prompt_language="en",
            answer_language=config.sampling.answer_language,
            round_index=0,
            sample_index=0,
            system_prompt=_diagnosis_system_prompt(),
            user_prompt=_diagnosis_user_prompt(rec),
            temperature=min(0.3, float(provider_config.temperature)),
            max_output_tokens=max_output_tokens,
            seed=None,
        )
        last_err: Exception | None = None
        response = None
        for attempt in range(provider_config.max_retries):
            try:
                response = provider.generate(req)
                if response.error:
                    raise RuntimeError(response.error)
                break
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                LOGGER.warning("Diagnosis attempt %s failed for %s: %s", attempt + 1, item_id, exc)
        if response is None:
            tag = "T_UNK"
            raw = str(last_err) if last_err else "no_response"
        else:
            raw = response.text
            tag = _parse_tag_from_text(raw)
        results.append({"item_id": item_id, "primary_tag": tag, "raw_response": raw})
        log_track_b_line(
            phase_index=2,
            phase_name=PHASE_DIAGNOSE,
            step_label="api_calls",
            step_done=idx,
            step_total=n_flag,
            detail=f"finished item_id={item_id} tag={tag}",
        )
    return results

