from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from coordbench.models import GenerationRequest, GenerationResponse
from coordbench.response_validation import response_validation_error
from coordbench.utils.files import ensure_dir, read_json, write_json


def cache_key_for_request(request: GenerationRequest) -> str:
    payload = json.dumps(request.to_cache_payload(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cache_path(cache_root: Path, provider: str, model: str, cache_key: str) -> Path:
    safe_model = model.replace("/", "__")
    return cache_root / provider / safe_model / f"{cache_key}.json"


def load_cached_response(
    cache_root: Path,
    request: GenerationRequest,
) -> GenerationResponse | None:
    path = cache_path(cache_root, request.provider, request.model, cache_key_for_request(request))
    if not path.exists():
        return None
    payload = dict(read_json(path))
    if response_validation_error(
        text=str(payload.get("text", "")),
        finish_reason=payload.get("finish_reason"),
        error=payload.get("error"),
    ):
        return None
    payload["cache_hit"] = True
    return GenerationResponse(**payload)


def save_cached_response(
    cache_root: Path,
    request: GenerationRequest,
    response: GenerationResponse,
) -> Path:
    path = cache_path(cache_root, request.provider, request.model, cache_key_for_request(request))
    ensure_dir(path.parent)
    write_json(path, asdict(response))
    return path
