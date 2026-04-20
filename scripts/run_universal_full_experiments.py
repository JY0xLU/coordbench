from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from coordbench.analysis import analyze_run
from coordbench.config import load_config
from coordbench.normalize import normalize_run
from coordbench.plots import plot_run
from coordbench.runner import run_sampling


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "configs" / "universal_api_full.yaml"
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "full_experiments"
RESULTS_ROOT = REPO_ROOT / "results" / "full_experiments" / "summaries"

MODELS: list[tuple[str, int]] = [
    ("qwen3-coder-plus", 6),
    ("glm-5", 6),
    ("qwen3.5-plus", 4),
    ("gpt-5.4-mini", 6),
]

MODEL_PRICE_TIERS = {
    "qwen3-coder-plus": "1x",
    "glm-5": "unknown",
    "qwen3.5-plus": "1x",
    "gpt-5.4-mini": "2x",
}


@dataclass
class ExperimentSummary:
    model: str
    price_tier: str
    concurrency: int
    status: str
    run_dir: str
    wall_seconds: float
    completed_rounds: list[int]
    raw_record_count: int | None
    round2_candidate_count: int | None
    unresolved_count: int | None
    complete_cell_count: int | None
    incomplete_cell_count: int | None
    provider_errors: int
    empty_responses: int
    thought_pollution: int
    truncation_count: int
    cross_lingual_round1_jsd: float | None
    cross_lingual_round1_top1: float | None
    cross_lingual_round2_jsd: float | None
    cross_lingual_round2_top1: float | None
    human_alignment_en_round1_jsd: float | None
    human_alignment_zh_round1_jsd: float | None
    notes: str


def _safe_name(name: str) -> str:
    return name.replace("/", "__").replace(" ", "_")


def _read_json(path: Path) -> dict[str, Any] | list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _looks_like_thinking(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in ["thinking process", "<think>", "reasoning:", "analysis:", "let's think", "i think"]
    )


def _set_env(model: str, concurrency: int, run_root: Path, cache_root: Path) -> dict[str, str | None]:
    previous = {
        "UNIVERSAL_MODEL": os.environ.get("UNIVERSAL_MODEL"),
        "UNIVERSAL_CONCURRENCY": os.environ.get("UNIVERSAL_CONCURRENCY"),
        "UNIVERSAL_RUN_ROOT": os.environ.get("UNIVERSAL_RUN_ROOT"),
        "UNIVERSAL_CACHE_ROOT": os.environ.get("UNIVERSAL_CACHE_ROOT"),
    }
    os.environ["UNIVERSAL_MODEL"] = model
    os.environ["UNIVERSAL_CONCURRENCY"] = str(concurrency)
    os.environ["UNIVERSAL_RUN_ROOT"] = str(run_root)
    os.environ["UNIVERSAL_CACHE_ROOT"] = str(cache_root)
    return previous


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _summary_metric(summary_rows: list[dict[str, Any]], metric_family: str, round_index: int, prompt_language: str, field: str) -> float | None:
    for row in summary_rows:
        if (
            row.get("metric_family") == metric_family
            and int(row.get("round_index", 0)) == round_index
            and row.get("prompt_language") == prompt_language
        ):
            value = row.get(field)
            return None if value is None else float(value)
    return None


def _collect_summary(model: str, concurrency: int, run_dir: Path, wall_seconds: float, status: str, notes: str) -> ExperimentSummary:
    manifest_path = run_dir / "run_manifest.json"
    raw_rows = _read_jsonl(run_dir / "raw_generations.jsonl")
    if not manifest_path.exists():
        return ExperimentSummary(
            model=model,
            price_tier=MODEL_PRICE_TIERS.get(model, "unknown"),
            concurrency=concurrency,
            status=status,
            run_dir=str(run_dir),
            wall_seconds=round(wall_seconds, 2),
            completed_rounds=[],
            raw_record_count=len(raw_rows),
            round2_candidate_count=None,
            unresolved_count=None,
            complete_cell_count=None,
            incomplete_cell_count=None,
            provider_errors=0,
            empty_responses=0,
            thought_pollution=0,
            truncation_count=0,
            cross_lingual_round1_jsd=None,
            cross_lingual_round1_top1=None,
            cross_lingual_round2_jsd=None,
            cross_lingual_round2_top1=None,
            human_alignment_en_round1_jsd=None,
            human_alignment_zh_round1_jsd=None,
            notes=f"{notes}; run_manifest_missing",
        )

    manifest = _read_json(manifest_path)
    provider_errors = 0
    empty_responses = 0
    thought_pollution = 0
    truncation_count = 0

    for row in raw_rows:
        text = str(row.get("response_text", "") or "")
        if str(row.get("response_source", "") or "") == "provider_error" or str(row.get("error", "") or ""):
            provider_errors += 1
        if not text.strip():
            empty_responses += 1
        if _looks_like_thinking(text):
            thought_pollution += 1
        if str(row.get("finish_reason", "") or "").lower() in {"length", "max_tokens"}:
            truncation_count += 1

    summary_rows: list[dict[str, Any]] = []
    summary_path = run_dir / "summary_metrics.json"
    if summary_path.exists():
        raw_summary = _read_json(summary_path)
        if isinstance(raw_summary, list):
            summary_rows = raw_summary

    return ExperimentSummary(
        model=model,
        price_tier=MODEL_PRICE_TIERS.get(model, "unknown"),
        concurrency=concurrency,
        status=status,
        run_dir=str(run_dir),
        wall_seconds=round(wall_seconds, 2),
        completed_rounds=list(manifest.get("completed_rounds", [])),
        raw_record_count=manifest.get("raw_record_count"),
        round2_candidate_count=manifest.get("round2_candidate_count"),
        unresolved_count=manifest.get("unresolved_count"),
        complete_cell_count=manifest.get("complete_cell_count"),
        incomplete_cell_count=manifest.get("incomplete_cell_count"),
        provider_errors=provider_errors,
        empty_responses=empty_responses,
        thought_pollution=thought_pollution,
        truncation_count=truncation_count,
        cross_lingual_round1_jsd=_summary_metric(summary_rows, "cross_lingual", 1, "en_vs_zh", "mean_jsd"),
        cross_lingual_round1_top1=_summary_metric(summary_rows, "cross_lingual", 1, "en_vs_zh", "mean_top1_match"),
        cross_lingual_round2_jsd=_summary_metric(summary_rows, "cross_lingual", 2, "en_vs_zh", "mean_jsd"),
        cross_lingual_round2_top1=_summary_metric(summary_rows, "cross_lingual", 2, "en_vs_zh", "mean_top1_match"),
        human_alignment_en_round1_jsd=_summary_metric(summary_rows, "human_alignment", 1, "en", "mean_jsd"),
        human_alignment_zh_round1_jsd=_summary_metric(summary_rows, "human_alignment", 1, "zh", "mean_jsd"),
        notes=notes,
    )


def _run_model(root_dir: Path, model: str, concurrency: int) -> ExperimentSummary:
    safe_model = _safe_name(model)
    model_root = root_dir / safe_model
    run_root = model_root / "runs"
    cache_root = model_root / "cache"
    run_root.mkdir(parents=True, exist_ok=True)
    cache_root.mkdir(parents=True, exist_ok=True)

    previous = _set_env(model, concurrency, run_root, cache_root)
    run_dir: Path | None = None
    start = time.monotonic()
    notes = "completed"
    status = "completed"

    try:
        run_dir = run_sampling(CONFIG_PATH, round_index=1)
        normalize_run(CONFIG_PATH, run_dir)
        analyze_run(CONFIG_PATH, run_dir)

        candidates_path = run_dir / "round2_candidates.csv"
        if candidates_path.exists():
            candidates = pd.read_csv(candidates_path)
            item_ids = candidates["item_id"].dropna().astype(str).tolist()
            if item_ids:
                run_sampling(CONFIG_PATH, run_dir=run_dir, round_index=2, item_ids=item_ids)
                normalize_run(CONFIG_PATH, run_dir)
                analyze_run(CONFIG_PATH, run_dir)

        plot_run(CONFIG_PATH, run_dir)
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        notes = str(exc)
        if run_dir is None:
            config = load_config(CONFIG_PATH)
            maybe_runs = sorted(
                [
                    path
                    for path in Path(config.outputs.run_root).glob("*")
                    if (path / "run_manifest.json").exists()
                ],
                key=lambda path: path.name,
            )
            run_dir = maybe_runs[-1] if maybe_runs else model_root
    finally:
        _restore_env(previous)

    assert run_dir is not None
    return _collect_summary(model, concurrency, run_dir, time.monotonic() - start, status, notes)


def _write_summary(root_dir: Path, rows: list[ExperimentSummary]) -> tuple[Path, Path]:
    json_path = root_dir / "summary.json"
    md_path = RESULTS_ROOT / f"full_experiment_summary_{root_dir.name}.md"

    json_path.write_text(
        json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines: list[str] = []
    lines.append(f"# Full Experiment Summary {root_dir.name}")
    lines.append("")
    lines.append("| Model | Price | Concurrency | Status | Wall (s) | Raw | Round2 | Unresolved | Cross JSD R1 | Cross Top1 R1 | Human EN JSD | Human ZH JSD |")
    lines.append("| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in rows:
        lines.append(
            f"| {row.model} | {row.price_tier} | {row.concurrency} | {row.status} | {row.wall_seconds:.2f} | "
            f"{row.raw_record_count if row.raw_record_count is not None else ''} | "
            f"{row.round2_candidate_count if row.round2_candidate_count is not None else ''} | "
            f"{row.unresolved_count if row.unresolved_count is not None else ''} | "
            f"{row.cross_lingual_round1_jsd if row.cross_lingual_round1_jsd is not None else ''} | "
            f"{row.cross_lingual_round1_top1 if row.cross_lingual_round1_top1 is not None else ''} | "
            f"{row.human_alignment_en_round1_jsd if row.human_alignment_en_round1_jsd is not None else ''} | "
            f"{row.human_alignment_zh_round1_jsd if row.human_alignment_zh_round1_jsd is not None else ''} |"
        )

    lines.append("")
    lines.append("## Notes")
    lines.append("")
    for row in rows:
        lines.append(
            f"- `{row.model}`: status={row.status}, provider_errors={row.provider_errors}, "
            f"empty_responses={row.empty_responses}, thinking={row.thought_pollution}, "
            f"truncation={row.truncation_count}, run_dir=`{row.run_dir}`"
        )
        if row.notes and row.notes != "completed":
            lines.append(f"  note={row.notes}")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> int:
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%SZ")
    root_dir = ARTIFACT_ROOT / timestamp
    root_dir.mkdir(parents=True, exist_ok=True)
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)

    rows: list[ExperimentSummary] = []
    for model, concurrency in MODELS:
        print(f"[full-run] model={model} concurrency={concurrency}", flush=True)
        rows.append(_run_model(root_dir, model, concurrency))
        json_path, md_path = _write_summary(root_dir, rows)
        print(f"partial_summary_json={json_path}", flush=True)
        print(f"partial_summary_md={md_path}", flush=True)

    json_path, md_path = _write_summary(root_dir, rows)
    print(f"summary_json={json_path}")
    print(f"summary_md={md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
