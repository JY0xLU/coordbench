from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

from coordbench.utils.files import append_jsonl as _append_one_jsonl
from coordbench.utils.files import ensure_dir, read_json, read_jsonl, write_csv, write_json, write_jsonl
from coordbench.utils.text import ascii_fold, clean_surface, make_match_key


def append_jsonl(path: Path, rows) -> None:
    if isinstance(rows, dict):
        _append_one_jsonl(path, rows)
        return
    for row in rows:
        _append_one_jsonl(path, row)


def deterministic_cleanup(value: str) -> str:
    return clean_surface(value).lower()


def folded_key(value: str) -> str:
    return make_match_key(value)


def entropy_from_probs(probs: list[float]) -> float:
    import math

    return float(-sum(prob * math.log2(prob) for prob in probs if prob > 0))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def utc_now_stamp() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def env_or_none(name: str) -> str | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    return value.strip()


__all__ = [
    "append_jsonl",
    "ascii_fold",
    "clean_surface",
    "deterministic_cleanup",
    "ensure_dir",
    "entropy_from_probs",
    "env_or_none",
    "folded_key",
    "make_match_key",
    "read_json",
    "read_jsonl",
    "sha256_text",
    "utc_now_stamp",
    "write_csv",
    "write_json",
    "write_jsonl",
]
