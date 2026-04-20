from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def data_root() -> Path:
    return repo_root() / "data"


def source_root() -> Path:
    return data_root() / "source"


def prepared_root() -> Path:
    return data_root() / "prepared"


def aliases_path() -> Path:
    return data_root() / "aliases" / "default_aliases.csv"


def artifacts_root() -> Path:
    return repo_root() / "artifacts"
