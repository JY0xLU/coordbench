from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from coordbench.cache import cache_key_for_request
from coordbench.dataset.profile import latest_prepared_snapshot
from coordbench.models import GenerationRequest
from coordbench.paths import prepared_root
from coordbench.response_validation import response_validation_error
from coordbench.utils.files import read_json, read_jsonl

LOGGER = logging.getLogger(__name__)

REQUEST_IDENTITY_FIELDS = (
    "provider",
    "model",
    "panel_id",
    "item_id",
    "prompt_language",
    "answer_language",
    "round_index",
    "sample_index",
)


def resolve_run_dir(run_root: Path, run_id: str | Path) -> Path:
    run_dir = Path(run_id)
    return run_dir if run_dir.is_absolute() else run_root / str(run_id)


def load_run_manifest(run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.exists():
        hint = (
            " Use an absolute path to the run directory as --run-id if this run was created "
            "under a different config `outputs.run_root` (e.g. Track B with run_root under results/runs_s50)."
        )
        if not run_dir.exists():
            hint = (
                " The run directory does not exist at this path (check config run_root vs where sampling wrote files)."
                + hint
            )
        raise FileNotFoundError(f"Run manifest not found: {manifest_path}\n{hint}")
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ValueError(f"Run manifest is not a JSON object: {manifest_path}")
    return manifest


def prepared_snapshot_dir_for_manifest(manifest: dict[str, Any]) -> Path:
    snapshot_id = str(manifest.get("prepared_snapshot_id", "")).strip()
    if not snapshot_id:
        raise KeyError("Run manifest is missing `prepared_snapshot_id`; cannot safely resolve the bound dataset snapshot.")
    target = prepared_root() / snapshot_id
    if not target.exists():
        raise FileNotFoundError(f"Prepared snapshot from run manifest does not exist: {target}")
    return target


def prepared_snapshot_dir_for_run(run_dir: Path) -> Path:
    return prepared_snapshot_dir_for_manifest(load_run_manifest(run_dir))


def request_fallback_identity_from_mapping(record: dict[str, Any]) -> str:
    return "|".join(str(record.get(field, "")).strip() for field in REQUEST_IDENTITY_FIELDS)


def request_identity_from_record(record: dict[str, Any]) -> str:
    cache_key = str(record.get("request_cache_key", "")).strip()
    if cache_key:
        return cache_key
    return request_fallback_identity_from_mapping(record)


def request_identity_from_request(request: GenerationRequest) -> str:
    return cache_key_for_request(request)


def request_fallback_identity_from_request(request: GenerationRequest) -> str:
    request_mapping = {
        "provider": request.provider,
        "model": request.model,
        "panel_id": request.panel_id,
        "item_id": request.item_id,
        "prompt_language": request.prompt_language,
        "answer_language": request.answer_language,
        "round_index": request.round_index,
        "sample_index": request.sample_index,
    }
    return request_fallback_identity_from_mapping(request_mapping)


def record_is_complete(record: dict[str, Any]) -> bool:
    return response_validation_error(
        text=str(record.get("response_text") or record.get("text") or ""),
        finish_reason=record.get("finish_reason"),
        error=record.get("error"),
    ) is None


def completed_request_ids(raw_path: Path) -> set[str]:
    if not raw_path.exists():
        return set()
    identities: set[str] = set()
    for record in read_jsonl(raw_path):
        if record_is_complete(record):
            identities.add(request_identity_from_record(record))
            # Keep backward-compatible resume behavior when cache-key construction
            # changes between versions: also index by stable fallback identity.
            identities.add(request_fallback_identity_from_mapping(record))
    return identities


def _record_priority(record: dict[str, Any]) -> tuple[int, int, int, str]:
    source_priority = {
        "provider_api": 3,
        "disk_cache": 2,
        "provider_error": 1,
    }
    return (
        1 if record_is_complete(record) else 0,
        1 if str(record.get("response_text") or "").strip() else 0,
        source_priority.get(str(record.get("response_source") or ""), 0),
        str(record.get("generated_at_utc") or ""),
    )


def dedupe_request_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for record in records:
        identity = request_identity_from_record(record)
        existing = deduped.get(identity)
        if existing is None or _record_priority(record) > _record_priority(existing):
            deduped[identity] = record
    return list(deduped.values())


def latest_prepared_snapshot_or_raise() -> Path:
    prepared_dir = latest_prepared_snapshot()
    if prepared_dir is None:
        raise FileNotFoundError("No prepared dataset found. Run fetch-source-data and prepare-human-panels first.")
    return prepared_dir
