from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import requests

from coordbench.models import SourceAsset
from coordbench.paths import source_root
from coordbench.utils.files import ensure_dir, sha256sum, write_json

LOGGER = logging.getLogger(__name__)
UTC = getattr(__import__("datetime"), "UTC", timezone.utc)

OSF_ASSETS = [
    SourceAsset("datasets", "Study1.csv", "https://osf.io/download/nb52s/"),
    SourceAsset("datasets", "Study1b.csv", "https://osf.io/download/fdhyn/"),
    SourceAsset("datasets", "Study2.csv", "https://osf.io/download/gr7eh/"),
    SourceAsset("datasets", "Study3.csv", "https://osf.io/download/k9a7u/"),
    SourceAsset("datasets", "Study1c.xlsx", "https://osf.io/download/3a2s9/"),
    SourceAsset("materials", "Table_of_Alignment_Items.docx", "https://osf.io/download/ycgbx/"),
    SourceAsset("materials", "Instructions_International_Alignment_Study.docx", "https://osf.io/download/ndtqw/"),
    SourceAsset("materials", "Supplementary_Materials.docx", "https://osf.io/download/68c1a232d4c497369403576d/"),
    SourceAsset("materials", "RScriptForInternationalAlignmentPaper.html", "https://osf.io/download/2k8cd/"),
    SourceAsset(
        "materials",
        "Leave_One_Out_Bootstrapping.html",
        "https://osf.io/download/68c19cf906e4e24ebf5d82f0/",
    ),
]


def latest_source_snapshot(root: Path | None = None) -> Path | None:
    root = root or source_root()
    latest_pointer = root / "osf_fv47d" / "LATEST.txt"
    if not latest_pointer.exists():
        return None
    snapshot_id = latest_pointer.read_text(encoding="utf-8").strip()
    snapshot_dir = root / "osf_fv47d" / snapshot_id
    return snapshot_dir if snapshot_dir.exists() else None


def fetch_source_data(root: Path | None = None) -> Path:
    root = root or source_root()
    snapshot_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    snapshot_dir = ensure_dir(root / "osf_fv47d" / snapshot_id)
    LOGGER.info("Downloading OSF source data into %s", snapshot_dir)

    manifest_files: list[dict[str, str | int]] = []
    session = requests.Session()
    for asset in OSF_ASSETS:
        target_dir = ensure_dir(snapshot_dir / asset.category)
        target_path = target_dir / asset.name
        response = session.get(asset.url, timeout=180)
        response.raise_for_status()
        target_path.write_bytes(response.content)
        manifest_files.append(
            {
                "category": asset.category,
                "name": asset.name,
                "url": asset.url,
                "sha256": sha256sum(target_path),
                "bytes": target_path.stat().st_size,
            }
        )
        LOGGER.info("Downloaded %s", target_path.name)

    manifest = {
        "project_id": "fv47d",
        "downloaded_at_utc": datetime.now(UTC).isoformat(),
        "snapshot_id": snapshot_id,
        "files": manifest_files,
        "source_assets": [asdict(asset) for asset in OSF_ASSETS],
    }
    write_json(snapshot_dir / "source_manifest.json", manifest)
    ensure_dir(root / "osf_fv47d").joinpath("LATEST.txt").write_text(snapshot_id, encoding="utf-8")
    return snapshot_dir
