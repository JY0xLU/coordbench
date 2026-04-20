from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from coordbench.analysis import analyze_run
from coordbench.config import load_config
from coordbench.normalize import normalize_run
from coordbench.run_state import load_run_manifest, prepared_snapshot_dir_for_manifest
from coordbench.utils.files import ensure_dir, read_json, read_jsonl, write_json

from track_b_agent.flags import TrackBConfig, write_track_b_artifacts
from track_b_agent.integrated.diagnosis import diagnose_flagged_items
from track_b_agent.integrated.progress import (
    PHASE_ANALYZE,
    PHASE_DIAGNOSE,
    PHASE_FLAG,
    PHASE_NORMALIZE,
    PHASE_REPORT,
    log_track_b_line,
)
from track_b_agent.integrated.report import write_track_b_report
from track_b_agent.integrated.sampling import run_track_b_sampling
from track_b_agent.integrated.templates import load_repair_templates, load_tag_to_repair, repair_template_for_tag

LOGGER = logging.getLogger(__name__)
UTC = getattr(__import__("datetime"), "UTC", __import__("datetime").timezone.utc)

DEFAULT_REPAIR_ROUND = 3
DEFAULT_SHAM_ROUND = 4


def _resolve_run_dir(config_path: str | Path, run_id: str | Path) -> Path:
    config = load_config(config_path)
    path = Path(run_id)
    return path if path.is_absolute() else config.outputs.run_root / str(run_id)


def _infer_baseline_provider(baseline_dir: Path) -> str | None:
    raw_path = baseline_dir / "raw_generations.jsonl"
    if not raw_path.exists():
        return None
    for record in read_jsonl(raw_path):
        if record.get("error") not in {None, ""}:
            continue
        prov = record.get("provider")
        if prov:
            return str(prov).strip()
    return None


def _pick_provider_name(config: Any, baseline_dir: Path, override: str | None) -> str:
    if override:
        name = override.strip()
        if name not in config.providers:
            raise ValueError(f"Unknown provider `{name}` in config.")
        return name
    inferred = _infer_baseline_provider(baseline_dir)
    if inferred and inferred in config.providers and config.providers[inferred].enabled:
        return inferred
    enabled = [n for n, p in config.providers.items() if p.enabled]
    if len(enabled) == 1:
        return enabled[0]
    raise ValueError(
        "Could not pick a provider: set exactly one enabled provider in the benchmark config "
        "or pass --provider matching the baseline run."
    )


def run_track_b(
    coordbench_config: str | Path,
    baseline_run: str | Path,
    *,
    track_b_config: str | Path,
    repair_templates_yaml: str | Path,
    tag_map_yaml: str | Path,
    provider: str | None = None,
    stub_diagnose: bool = False,
    diagnosis_max_output_tokens: int = 256,
    repair_round: int = DEFAULT_REPAIR_ROUND,
    sham_round: int = DEFAULT_SHAM_ROUND,
) -> Path:
    """End-to-end Track B runner living under Agent/ but executing via coordbench core."""
    config = load_config(coordbench_config)
    baseline_dir = _resolve_run_dir(coordbench_config, baseline_run).resolve()
    if not baseline_dir.is_dir():
        raise FileNotFoundError(f"Baseline run directory not found: {baseline_dir}")
    item_metrics_path = baseline_dir / "item_metrics.csv"
    if not item_metrics_path.exists():
        raise FileNotFoundError(f"Baseline item_metrics.csv missing: {item_metrics_path}")

    base_manifest = load_run_manifest(baseline_dir)
    panel_id = str(base_manifest.get("panel_id") or config.sampling.panel_id)
    if str(config.sampling.panel_id) != panel_id:
        raise ValueError(f"Config panel_id `{config.sampling.panel_id}` does not match baseline `{panel_id}`.")

    tb_cfg = TrackBConfig.from_yaml(Path(track_b_config))
    provider_name = _pick_provider_name(config, baseline_dir, provider)
    prepared_dir = prepared_snapshot_dir_for_manifest(base_manifest)

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = ensure_dir(config.outputs.run_root / f"track_b_{run_id}")
    LOGGER.info("Track B run directory: %s", run_dir)

    write_track_b_artifacts(run_dir, item_metrics_path, tb_cfg, panel_id=panel_id)
    flagged = json.loads((run_dir / "flagged_items.json").read_text(encoding="utf-8"))
    controls = json.loads((run_dir / "unflagged_controls.json").read_text(encoding="utf-8"))
    all_ids = [str(r["item_id"]) for r in flagged + controls]
    log_track_b_line(
        phase_index=1,
        phase_name=PHASE_FLAG,
        step_label="write_artifacts",
        step_done=1,
        step_total=1,
        detail=f"flagged={len(flagged)} controls={len(controls)} item_ids={len(all_ids)}",
    )

    repair_templates = load_repair_templates(Path(repair_templates_yaml))
    tag_map = load_tag_to_repair(Path(tag_map_yaml))

    if stub_diagnose:
        log_track_b_line(
            phase_index=2,
            phase_name=PHASE_DIAGNOSE,
            step_label="stub_tags",
            step_done=1,
            step_total=1,
            detail="--stub-diagnose (no LLM calls)",
        )
        diagnosis_rows = [
            {"item_id": str(r["item_id"]), "primary_tag": "T_UNK", "raw_response": "stub"} for r in flagged
        ]
    else:
        diagnosis_rows = diagnose_flagged_items(
            config,
            provider_name,
            flagged,
            max_output_tokens=diagnosis_max_output_tokens,
        )
    (run_dir / "track_b_diagnoses.json").write_text(
        json.dumps(diagnosis_rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    tag_by_item = {str(r["item_id"]): str(r["primary_tag"]) for r in diagnosis_rows}
    repair_template_by_item: dict[str, str] = {}
    plan: list[dict[str, Any]] = []
    for r in flagged:
        iid = str(r["item_id"])
        tag = tag_by_item.get(iid, "T_UNK")
        rt = repair_template_for_tag(tag, tag_map)
        repair_template_by_item[iid] = rt
        plan.append({"item_id": iid, "cohort": "flagged", "primary_tag": tag, "repair_template": rt})
    for r in controls:
        iid = str(r["item_id"])
        repair_template_by_item[iid] = "R_COORD"
        plan.append({"item_id": iid, "cohort": "control", "primary_tag": "", "repair_template": "R_COORD"})

    (run_dir / "track_b_plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    manifest = {
        "run_id": run_dir.name,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "config_path": str(Path(coordbench_config).resolve()),
        "prepared_snapshot_id": base_manifest["prepared_snapshot_id"],
        "prepared_snapshot_path": str(prepared_dir.resolve()),
        "panel_id": panel_id,
        "prompt_languages": config.sampling.prompt_languages,
        "answer_language": config.sampling.answer_language,
        "configured_item_ids": all_ids,
        "track_b": True,
        "baseline_run_path": str(baseline_dir),
        "baseline_run_id": baseline_dir.name,
        "track_b_provider": provider_name,
        "track_b_repair_round": repair_round,
        "track_b_sham_round": sham_round,
        "completed_rounds": [],
    }
    write_json(run_dir / "run_manifest.json", manifest)

    run_track_b_sampling(
        config,
        run_dir,
        prepared_dir,
        provider_name,
        repair_round=repair_round,
        sham_round=sham_round,
        repair_template_by_item=repair_template_by_item,
        item_ids=all_ids,
        repair_templates=repair_templates,
    )

    mpath = run_dir / "run_manifest.json"
    manifest_after = read_json(mpath)
    manifest_after.setdefault("completed_rounds", [])
    for r in (repair_round, sham_round):
        if int(r) not in [int(x) for x in manifest_after["completed_rounds"]]:
            manifest_after["completed_rounds"].append(int(r))
    write_json(mpath, manifest_after)

    log_track_b_line(
        phase_index=4,
        phase_name=PHASE_NORMALIZE,
        step_label="normalize_run",
        step_done=0,
        step_total=1,
        detail=f"run_id={run_dir.name}",
    )
    normalize_run(coordbench_config, run_dir.name, allow_unmapped_override=True)
    log_track_b_line(
        phase_index=4,
        phase_name=PHASE_NORMALIZE,
        step_label="normalize_run",
        step_done=1,
        step_total=1,
        detail="finished",
    )

    log_track_b_line(
        phase_index=5,
        phase_name=PHASE_ANALYZE,
        step_label="analyze_run",
        step_done=0,
        step_total=1,
        detail=f"run_id={run_dir.name}",
    )
    analyze_run(coordbench_config, run_dir.name)
    log_track_b_line(
        phase_index=5,
        phase_name=PHASE_ANALYZE,
        step_label="analyze_run",
        step_done=1,
        step_total=1,
        detail="finished",
    )

    log_track_b_line(
        phase_index=6,
        phase_name=PHASE_REPORT,
        step_label="write_markdown",
        step_done=0,
        step_total=1,
        detail="track_b_report.md",
    )
    write_track_b_report(
        baseline_dir,
        run_dir,
        panel_id=panel_id,
        baseline_round=1,
        repair_round=repair_round,
        sham_round=sham_round,
    )
    log_track_b_line(
        phase_index=6,
        phase_name=PHASE_REPORT,
        step_label="write_markdown",
        step_done=1,
        step_total=1,
        detail="finished",
    )
    LOGGER.info("Track B complete. Report: %s", run_dir / "track_b_report.md")
    return run_dir

