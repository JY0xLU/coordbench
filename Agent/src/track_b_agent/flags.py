from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


@dataclass
class TrackBConfig:
    track_b_version: str
    baseline_definition: str
    use_f1: bool
    use_f2: bool
    tau_xling: float
    use_f3: bool
    tau_human: float
    max_flagged_items: int
    unflagged_control_count: int
    frozen_track_a_commit: str

    @classmethod
    def from_yaml(cls, path: Path) -> TrackBConfig:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        r = raw.get("rules") or {}
        return cls(
            track_b_version=str(raw.get("track_b_version", "0.1.0")),
            baseline_definition=str(raw.get("baseline_definition", "track_a_round1_only")),
            use_f1=bool(r.get("use_f1", True)),
            use_f2=bool(r.get("use_f2", False)),
            tau_xling=float(r.get("tau_xling", 0.25)),
            use_f3=bool(r.get("use_f3", False)),
            tau_human=float(r.get("tau_human", 0.35)),
            max_flagged_items=int(raw.get("max_flagged_items", 8)),
            unflagged_control_count=int(raw.get("unflagged_control_count", 3)),
            frozen_track_a_commit=str(raw.get("frozen_track_a_commit", "")),
        )


def _strip_human_fields(row: pd.Series) -> dict[str, Any]:
    """Metrics snapshot without human-benchmark columns (plan §3.3)."""
    d = row.to_dict()
    for k in (
        "human_top1_probability",
        "consensus_bucket",
    ):
        d.pop(k, None)
    return {k: v for k, v in d.items() if pd.notna(v)}


def select_flagged_and_controls(
    item_metrics_path: Path,
    config: TrackBConfig,
    *,
    panel_id: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Return (flagged_records, unflagged_records, manifest_extras)."""
    if not config.use_f1:
        raise ValueError("track_b: use_f1 must be true for MVP (see agent_plan.md §3.1).")

    df = pd.read_csv(item_metrics_path)
    x = df[(df["metric_family"] == "cross_lingual") & (df["round_index"] == 1)].copy()
    if panel_id is not None:
        x = x[x["panel_id"] == panel_id]
    if x.empty:
        raise ValueError("No cross_lingual round_index==1 rows (check panel_id filter).")

    # F1 ∧ optional F2 on same frame
    mask = x["top1_match"] == 0
    rules_note: list[str] = ["F1"]
    if config.use_f2:
        mask &= x["jsd"] >= config.tau_xling
        rules_note.append("F2")

    flagged_df = x.loc[mask].copy()
    flagged_df = flagged_df.sort_values(by=["jsd", "item_id"], ascending=[False, True])
    if len(flagged_df) > config.max_flagged_items:
        flagged_df = flagged_df.iloc[: config.max_flagged_items]

    flagged_ids = set(flagged_df["item_id"].astype(str))
    flagged_records: list[dict[str, Any]] = []
    for _, row in flagged_df.iterrows():
        flagged_records.append(
            {
                "item_id": str(row["item_id"]),
                "item_number": int(row["item_number"]),
                "rules_fired": list(rules_note),
                "metrics_snapshot": _strip_human_fields(row),
            }
        )

    # F3 optional: extra flagged from human_alignment (not merged into MVP list unless we want)
    if config.use_f3:
        h = df[
            (df["metric_family"] == "human_alignment")
            & (df["round_index"] == 1)
            & (df["prompt_language"] == "en")
        ]
        if panel_id is not None:
            h = h[h["panel_id"] == panel_id]
        h = h[h["jsd"] >= config.tau_human]
        # For MVP we only append item_ids not already flagged, up to same N budget — skip to avoid complexity; document in manifest
        manifest_extra_f3 = {"f3_candidate_count": int(h["item_id"].nunique())}
    else:
        manifest_extra_f3 = {}

    # Unflagged controls (plan §7.1.1)
    stable = x[(x["top1_match"] == 1) & (~x["item_id"].astype(str).isin(flagged_ids))].copy()
    stable = stable.sort_values(by=["jsd", "item_id"], ascending=[True, True])
    warning = None
    k = config.unflagged_control_count
    if len(stable) < k:
        warning = f"only_{len(stable)}_candidates_for_unflagged"
        pick = stable
    else:
        pick = stable.iloc[:k]

    unflagged_records: list[dict[str, Any]] = []
    for _, row in pick.iterrows():
        unflagged_records.append(
            {
                "item_id": str(row["item_id"]),
                "item_number": int(row["item_number"]),
                "jsd_at_select": float(row["jsd"]),
                "rule": "cross_lingual_r1_top1_match_eq_1_stable_sort",
                "metrics_snapshot": _strip_human_fields(row),
            }
        )

    extras = {
        "unflagged_control_warning": warning,
        **manifest_extra_f3,
    }
    return flagged_records, unflagged_records, extras


def write_track_b_artifacts(
    out_dir: Path,
    item_metrics_path: Path,
    config: TrackBConfig,
    *,
    panel_id: str | None = None,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    flagged, unflagged, extras = select_flagged_and_controls(
        item_metrics_path, config, panel_id=panel_id
    )

    (out_dir / "flagged_items.json").write_text(
        json.dumps(flagged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out_dir / "unflagged_controls.json").write_text(
        json.dumps(unflagged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    manifest = {
        "track_b_version": config.track_b_version,
        "baseline_definition": config.baseline_definition,
        "TRACK_B_BASELINE": config.baseline_definition,
        "item_metrics_source": str(item_metrics_path.resolve()),
        "max_flagged_items": config.max_flagged_items,
        "unflagged_control_count": config.unflagged_control_count,
        "flagged_count": len(flagged),
        "unflagged_control_selected": len(unflagged),
        "rules": {
            "use_f1": config.use_f1,
            "use_f2": config.use_f2,
            "tau_xling": config.tau_xling,
            "use_f3": config.use_f3,
            "tau_human": config.tau_human,
        },
        "frozen_track_a_commit": config.frozen_track_a_commit or None,
        **extras,
    }

    (out_dir / "track_b_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return out_dir
