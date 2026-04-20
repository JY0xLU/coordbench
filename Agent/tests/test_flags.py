from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from track_b_agent.flags import TrackBConfig, select_flagged_and_controls, write_track_b_artifacts
from track_b_agent.repair_manifest import write_repair_manifest
from track_b_agent.diagnosis_stub import write_stub_diagnoses


def _minimal_metrics() -> pd.DataFrame:
    rows = []
    base = {
        "metric_family": "cross_lingual",
        "round_index": 1,
        "panel_id": "study2_british_within",
        "prompt_language": "en_vs_zh",
        "human_top1_probability": 0.5,
        "consensus_bucket": "medium",
    }
    # stable low jsd
    for i, jsd, tm in [(1, 0.05, 1), (2, 0.06, 1), (3, 0.07, 1), (4, 0.08, 1)]:
        rows.append(
            {
                **base,
                "provider": "p",
                "model": "m",
                "item_id": f"study2_item_{i:02d}",
                "item_number": i,
                "jsd": jsd,
                "tvd": 0.1,
                "top1_match": tm,
                "flip_rate": 0,
                "spearman": None,
                "successful_samples": 30,
                "expected_samples": 30,
                "completion_rate": 1.0,
                "en_successful_samples": 30,
                "zh_successful_samples": 30,
            }
        )
    # drift high jsd
    for i, jsd in [(5, 0.5), (6, 0.4), (7, 0.35)]:
        rows.append(
            {
                **base,
                "provider": "p",
                "model": "m",
                "item_id": f"study2_item_{i:02d}",
                "item_number": i,
                "jsd": jsd,
                "tvd": 0.3,
                "top1_match": 0,
                "flip_rate": 1,
                "spearman": 0.2,
                "successful_samples": 30,
                "expected_samples": 30,
                "completion_rate": 1.0,
                "en_successful_samples": 30,
                "zh_successful_samples": 30,
            }
        )
    return pd.DataFrame(rows)


def test_select_flagged_deterministic_order(tmp_path: Path) -> None:
    csv = tmp_path / "item_metrics.csv"
    _minimal_metrics().to_csv(csv, index=False)
    cfg = TrackBConfig(
        track_b_version="0",
        baseline_definition="track_a_round1_only",
        use_f1=True,
        use_f2=False,
        tau_xling=0.25,
        use_f3=False,
        tau_human=0.35,
        max_flagged_items=2,
        unflagged_control_count=2,
        frozen_track_a_commit="",
    )
    flagged, unflagged, _ = select_flagged_and_controls(csv, cfg)
    assert [r["item_id"] for r in flagged] == ["study2_item_05", "study2_item_06"]
    assert [r["item_id"] for r in unflagged] == ["study2_item_01", "study2_item_02"]


def test_end_to_end_manifest(tmp_path: Path) -> None:
    csv = tmp_path / "item_metrics.csv"
    _minimal_metrics().to_csv(csv, index=False)
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(
        """
track_b_version: "0.1.0"
baseline_definition: track_a_round1_only
rules:
  use_f1: true
  use_f2: false
max_flagged_items: 2
unflagged_control_count: 2
""",
        encoding="utf-8",
    )
    out = tmp_path / "tb"
    cfg = TrackBConfig.from_yaml(cfg_path)
    write_track_b_artifacts(out, csv, cfg)
    write_stub_diagnoses(out)
    tag_map = Path(__file__).resolve().parents[1] / "prompts" / "tag_to_repair.yaml"
    write_repair_manifest(out, tag_map)
    rm = (out / "repair_manifest.yaml").read_text(encoding="utf-8")
    assert "study2_item_05" in rm
    assert "R_SHAM" in rm
