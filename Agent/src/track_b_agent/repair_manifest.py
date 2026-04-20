from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from track_b_agent.constants import REPAIR_TEMPLATE_IDS, VALID_DIAGNOSIS_TAGS
from track_b_agent.templates import load_tag_to_repair, map_tag_to_repair


def _first_repair_tag(tags: list[str], tag_to_repair: dict[str, str]) -> str:
    for t in tags:
        if t in VALID_DIAGNOSIS_TAGS and t != "T_UNK":
            return map_tag_to_repair(t, tag_to_repair)
    return map_tag_to_repair("T_UNK", tag_to_repair)


def write_repair_manifest(
    out_dir: Path,
    tag_to_repair_path: Path,
) -> Path:
    """Combine flagged + unflagged + diagnosis → repair_manifest.yaml."""
    tag_to_repair = load_tag_to_repair(tag_to_repair_path)
    flagged = json.loads((out_dir / "flagged_items.json").read_text(encoding="utf-8"))
    unflagged = json.loads((out_dir / "unflagged_controls.json").read_text(encoding="utf-8"))
    diag_dir = out_dir / "diagnosis"
    items: list[dict[str, Any]] = []

    for rec in flagged:
        iid = rec["item_id"]
        diag_path = diag_dir / f"{iid}.json"
        tags = ["T_UNK"]
        if diag_path.exists():
            tags = json.loads(diag_path.read_text(encoding="utf-8")).get("tags") or ["T_UNK"]
        rt = _first_repair_tag(tags, tag_to_repair)
        if rt not in REPAIR_TEMPLATE_IDS or rt == "R_SHAM":
            rt = "R_COORD"
        items.append(
            {
                "item_id": iid,
                "cohort": "flagged",
                "repair_template_id": rt,
                "sham_template_id": "R_SHAM",
                "diagnosis_tags": tags,
            }
        )

    for rec in unflagged:
        iid = rec["item_id"]
        items.append(
            {
                "item_id": iid,
                "cohort": "unflagged_control",
                "repair_template_id": "R_COORD",
                "sham_template_id": "R_SHAM",
                "diagnosis_tags": [],
            }
        )

    manifest = {"track_b_arm_templates": items, "tag_to_repair_source": str(tag_to_repair_path)}
    out_path = out_dir / "repair_manifest.yaml"
    out_path.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return out_path
