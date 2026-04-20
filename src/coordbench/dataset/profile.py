from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import pandas as pd

from coordbench.paths import prepared_root
from coordbench.utils.files import read_json, write_json
from coordbench.utils.text import ascii_fold

LOGGER = logging.getLogger(__name__)


def latest_prepared_snapshot(root: Path | None = None) -> Path | None:
    root = root or prepared_root()
    latest_pointer = root / "LATEST.txt"
    if not latest_pointer.exists():
        return None
    snapshot_id = latest_pointer.read_text(encoding="utf-8").strip()
    target = root / snapshot_id
    return target if target.exists() else None


def _entropy(probabilities: list[float]) -> float:
    return float(-sum(p * math.log2(p) for p in probabilities if p > 0))


def _selection_score(row: pd.Series) -> tuple[float, int, int]:
    english_bonus = 1 if row["respondent_group"] == "british" and row["relation"] == "within" else 0
    item_bonus = 1 if 15 <= row["item_count"] <= 20 else 0
    return (english_bonus + item_bonus, int(row["respondent_count"]), int(row["item_count"]))


def profile_dataset(prepared_snapshot_dir: Path | None = None) -> Path:
    prepared_snapshot_dir = prepared_snapshot_dir or latest_prepared_snapshot()
    if prepared_snapshot_dir is None:
        raise FileNotFoundError("No prepared snapshot found. Run `coordbench prepare-human-panels` first.")

    participant = pd.read_csv(prepared_snapshot_dir / "participant_responses.csv")
    human = pd.read_csv(prepared_snapshot_dir / "human_distributions.csv")
    manifest = read_json(prepared_snapshot_dir / "benchmark_manifest.json")

    item_metrics = (
        human.groupby(["panel_id", "item_id"])
        .apply(
            lambda group: pd.Series(
                {
                    "top1_probability": float(group["probability"].max()),
                    "entropy": _entropy(group["probability"].tolist()),
                    "unique_answers": int(group["answer_key"].nunique()),
                }
            ),
            include_groups=False,
        )
        .reset_index()
    )

    participant["accent_folded"] = participant["response_clean"].astype(str).map(ascii_fold)
    participant["accent_changed"] = (
        participant["response_clean"].astype(str).str.lower()
        != participant["accent_folded"].astype(str).str.lower()
    )
    participant["spacing_changed"] = participant["response_original"].astype(str) != participant["response_clean"].astype(str)

    panel_summary = (
        participant.groupby(["panel_id", "study_id", "respondent_group", "target_group", "relation"])
        .agg(
            respondent_count=("participant_id", "nunique"),
            response_count=("response_original", "count"),
            item_count=("item_id", "nunique"),
            empty_response_count=("answer_key", lambda series: int((series == "").sum())),
            accent_changed_count=("accent_changed", "sum"),
            spacing_changed_count=("spacing_changed", "sum"),
        )
        .reset_index()
    )
    merged = panel_summary.merge(
        item_metrics.groupby("panel_id")
        .agg(
            mean_top1_probability=("top1_probability", "mean"),
            mean_entropy=("entropy", "mean"),
            mean_unique_answers=("unique_answers", "mean"),
        )
        .reset_index(),
        on="panel_id",
        how="left",
    )
    merged = merged.sort_values(["study_id", "respondent_group", "relation"]).reset_index(drop=True)
    merged.to_csv(prepared_snapshot_dir / "panel_summary.csv", index=False)

    ranked = sorted(
        merged.to_dict(orient="records"),
        key=lambda row: _selection_score(pd.Series(row)),
        reverse=True,
    )
    recommended_panel = ranked[0]["panel_id"] if ranked else manifest.get("default_panel_id", "")
    manifest["recommended_panel_id"] = recommended_panel
    manifest["default_panel_id"] = "study2_british_within"
    write_json(prepared_snapshot_dir / "benchmark_manifest.json", manifest)

    inventory = {
        "prepared_snapshot_id": manifest["prepared_snapshot_id"],
        "recommended_panel_id": recommended_panel,
        "default_panel_id": "study2_british_within",
        "panels": merged.to_dict(orient="records"),
        "items": item_metrics.to_dict(orient="records"),
    }
    write_json(prepared_snapshot_dir / "dataset_inventory.json", inventory)

    report_lines = [
        "# Dataset Selection Report",
        "",
        f"- Prepared snapshot: `{manifest['prepared_snapshot_id']}`",
        f"- Recommended default panel: `{recommended_panel}`",
        "- Policy rationale: prefer within-condition English panels with 15 to 20 items and the largest respondent counts.",
        "",
        "## Panel Summary",
        "",
    ]
    for row in ranked:
        report_lines.append(
            (
                f"- `{row['panel_id']}`: respondents={int(row['respondent_count'])}, "
                f"items={int(row['item_count'])}, mean_top1={row['mean_top1_probability']:.3f}, "
                f"mean_entropy={row['mean_entropy']:.3f}, relation={row['relation']}"
            )
        )
    report_lines.extend(
        [
            "",
            "## Recommendation",
            "",
            "- `study2_british_within` remains the official default because it offers 15 items, 100 respondents, and English human answers that match the fixed-English-output benchmark design.",
            "- Study 3 panels are prepared as secondary robustness datasets, especially useful for multilingual and cross-population follow-up analyses.",
        ]
    )
    (prepared_snapshot_dir / "selection_report.md").write_text("\n".join(report_lines), encoding="utf-8")
    LOGGER.info("Wrote dataset profile into %s", prepared_snapshot_dir)
    return prepared_snapshot_dir
