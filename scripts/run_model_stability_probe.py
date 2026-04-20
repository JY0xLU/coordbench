from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from coordbench.analysis import analyze_run
from coordbench.config import load_config
from coordbench.normalize import normalize_run
from coordbench.runner import run_sampling
from coordbench.run_state import latest_prepared_snapshot_or_raise


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "configs" / "universal_api_openai.yaml"
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "stability_probes"
RESULTS_ROOT = REPO_ROOT / "results" / "stability_probes"
DEFAULT_ITEM_COUNT = 5
DEFAULT_CONCURRENCY_LEVELS = [1, 2, 4]

FALLBACK_MODELS = [
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "gemini-3.1-flash",
    "gemini-3.1-flash-lite",
    "gemini-3.1-pro",
    "glm-5",
    "gpt-5.3-codex",
    "gpt-5.3-codex-spark",
    "gpt-5.4",
    "gpt-5.4-mini",
    "kimi-for-coding",
    "mimo-v2-omni",
    "mimo-v2-pro",
    "MiniMax-M2.7",
    "MiniMax-M2.7-highspeed",
    "qwen3-coder-plus",
    "qwen3.5-plus",
]

THINKING_MARKERS = ("thinking process", "<think>", "reasoning:", "analysis:", "let's think", "i think")


@dataclass
class ProbeRunSummary:
    model: str
    concurrency: int
    status: str
    note: str
    run_dir: str
    expected_records: int
    raw_record_count: int
    provider_errors: int
    empty_responses: int
    thinking_pollution: int
    truncation_count: int
    retry_record_count: int
    avg_latency_seconds: float | None
    max_latency_seconds: float | None
    unresolved_count: int | None
    round2_candidate_count: int | None
    cross_lingual_round1_jsd: float | None
    cross_lingual_round1_top1: float | None
    human_alignment_en_round1_jsd: float | None
    human_alignment_zh_round1_jsd: float | None
    sample_answers: list[str]


@dataclass
class ModelSummary:
    model: str
    tested_concurrencies: list[int]
    stable_concurrencies: list[int]
    recommended_concurrency: int | None
    status: str
    note: str
    best_run_dir: str


def _load_env() -> None:
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value)
    if not os.environ.get("UNIVERSAL_CONCURRENCY"):
        os.environ["UNIVERSAL_CONCURRENCY"] = "1"


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
    return any(marker in lowered for marker in THINKING_MARKERS)


def _model_pool() -> list[str]:
    base_url = str(os.environ.get("UNIVERSAL_BASE_URL", "https://api.mytokenland.com/v1")).rstrip("/")
    api_key = str(os.environ.get("UNIVERSAL_API_KEY", "")).strip()
    if not api_key:
        return list(FALLBACK_MODELS)

    session = requests.Session()
    session.trust_env = False
    try:
        response = session.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        models: list[str] = []
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                supported = item.get("supported_endpoint_types")
                if isinstance(supported, list):
                    supported_text = {str(value) for value in supported}
                    if "openai" not in supported_text:
                        continue
                model_id = str(item.get("id") or "").strip()
                if model_id:
                    models.append(model_id)
        models = list(dict.fromkeys(models))
        return models or list(FALLBACK_MODELS)
    except Exception:
        return list(FALLBACK_MODELS)


def _load_probe_item_ids(limit: int) -> tuple[str, list[str]]:
    config = load_config(CONFIG_PATH)
    prepared_dir = latest_prepared_snapshot_or_raise()
    panel = pd.read_csv(prepared_dir / "panel_items.csv")
    subset = panel[panel["panel_id"] == config.sampling.panel_id].copy()
    subset = subset.sort_values("item_number").head(limit)
    if subset.empty:
        raise RuntimeError(f"No items found for panel {config.sampling.panel_id}")
    item_ids = subset["item_id"].dropna().astype(str).tolist()
    return prepared_dir.name, item_ids


def _summary_metric(
    summary_rows: list[dict[str, Any]],
    metric_family: str,
    round_index: int,
    prompt_language: str,
    field: str,
) -> float | None:
    for row in summary_rows:
        if (
            row.get("metric_family") == metric_family
            and int(row.get("round_index", 0)) == round_index
            and row.get("prompt_language") == prompt_language
        ):
            value = row.get(field)
            return None if value is None else float(value)
    return None


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


def _extract_metrics(run_dir: Path, expected_records: int) -> ProbeRunSummary:
    raw_path = run_dir / "raw_generations.jsonl"
    manifest_path = run_dir / "run_manifest.json"

    raw_rows = _read_jsonl(raw_path)
    provider_errors = 0
    empty_responses = 0
    thinking_pollution = 0
    truncation_count = 0
    retry_record_count = 0
    latencies: list[float] = []
    sample_answers: list[str] = []

    for row in raw_rows:
        text = str(row.get("response_text", "") or "")
        error = str(row.get("error", "") or "")
        source = str(row.get("response_source", "") or "")
        finish_reason = str(row.get("finish_reason", "") or "").lower()
        retry_count = int(row.get("retry_count", 0) or 0)
        latency = row.get("latency_seconds")

        if retry_count > 0:
            retry_record_count += 1
        if latency is not None:
            latencies.append(float(latency))

        is_provider_error = source == "provider_error" or bool(error)
        is_empty = not text.strip()
        is_thinking = _looks_like_thinking(text)
        is_truncated = finish_reason in {"length", "max_tokens"}

        if is_provider_error:
            provider_errors += 1
        if is_empty:
            empty_responses += 1
        if is_thinking:
            thinking_pollution += 1
        if is_truncated:
            truncation_count += 1

        if not (is_provider_error or is_empty or is_thinking or is_truncated) and len(sample_answers) < 5:
            sample_answers.append(text.strip())

    unresolved_count = None
    round2_candidate_count = None
    cross_lingual_round1_jsd = None
    cross_lingual_round1_top1 = None
    human_alignment_en_round1_jsd = None
    human_alignment_zh_round1_jsd = None

    if manifest_path.exists():
        try:
            manifest = _read_json(manifest_path)
            if isinstance(manifest, dict):
                unresolved_count = manifest.get("unresolved_count")
                round2_candidate_count = manifest.get("round2_candidate_count")
        except Exception:
            pass

    summary_path = run_dir / "summary_metrics.json"
    if summary_path.exists():
        try:
            raw_summary = _read_json(summary_path)
            summary_rows = raw_summary if isinstance(raw_summary, list) else []
            cross_lingual_round1_jsd = _summary_metric(summary_rows, "cross_lingual", 1, "en_vs_zh", "mean_jsd")
            cross_lingual_round1_top1 = _summary_metric(summary_rows, "cross_lingual", 1, "en_vs_zh", "mean_top1_match")
            human_alignment_en_round1_jsd = _summary_metric(summary_rows, "human_alignment", 1, "en", "mean_jsd")
            human_alignment_zh_round1_jsd = _summary_metric(summary_rows, "human_alignment", 1, "zh", "mean_jsd")
        except Exception:
            pass

    status = "stable"
    note_parts: list[str] = []
    if len(raw_rows) != expected_records:
        status = "unstable"
        note_parts.append(f"raw_count={len(raw_rows)} expected={expected_records}")
    if provider_errors > 0:
        status = "unstable"
        note_parts.append(f"provider_errors={provider_errors}")
    if empty_responses > 0:
        status = "unstable"
        note_parts.append(f"empty_responses={empty_responses}")
    if thinking_pollution > 0:
        status = "unstable"
        note_parts.append(f"thinking_pollution={thinking_pollution}")
    if truncation_count > 0:
        status = "unstable"
        note_parts.append(f"truncation_count={truncation_count}")
    if retry_record_count > 0:
        note_parts.append(f"retry_records={retry_record_count}")

    return ProbeRunSummary(
        model=str(raw_rows[0].get("model", "")) if raw_rows else "",
        concurrency=int(raw_rows[0].get("provider_concurrency", 0) or 0) if raw_rows else 0,
        status=status,
        note="; ".join(note_parts) if note_parts else "ok",
        run_dir=str(run_dir),
        expected_records=expected_records,
        raw_record_count=len(raw_rows),
        provider_errors=provider_errors,
        empty_responses=empty_responses,
        thinking_pollution=thinking_pollution,
        truncation_count=truncation_count,
        retry_record_count=retry_record_count,
        avg_latency_seconds=round(statistics.mean(latencies), 2) if latencies else None,
        max_latency_seconds=round(max(latencies), 2) if latencies else None,
        unresolved_count=int(unresolved_count) if unresolved_count is not None else None,
        round2_candidate_count=int(round2_candidate_count) if round2_candidate_count is not None else None,
        cross_lingual_round1_jsd=cross_lingual_round1_jsd,
        cross_lingual_round1_top1=cross_lingual_round1_top1,
        human_alignment_en_round1_jsd=human_alignment_en_round1_jsd,
        human_alignment_zh_round1_jsd=human_alignment_zh_round1_jsd,
        sample_answers=sample_answers,
    )


def _run_probe(
    *,
    model: str,
    concurrency: int,
    batch_tag: str,
    item_ids: list[str],
) -> ProbeRunSummary:
    safe_model = _safe_name(model)
    run_root = ARTIFACT_ROOT / batch_tag / safe_model / f"c{concurrency}"
    cache_root = ARTIFACT_ROOT / batch_tag / "cache" / safe_model / f"c{concurrency}"
    run_root.mkdir(parents=True, exist_ok=True)
    cache_root.mkdir(parents=True, exist_ok=True)

    previous = _set_env(model, concurrency, run_root, cache_root)
    start = time.monotonic()
    run_dir: Path | None = None
    try:
        run_dir = run_sampling(CONFIG_PATH, round_index=1, item_ids=item_ids)
        raw_count = len(_read_jsonl(run_dir / "raw_generations.jsonl"))
        if raw_count > 0:
            normalize_run(CONFIG_PATH, run_dir)
            analyze_run(CONFIG_PATH, run_dir)
        expected_records = len(item_ids) * len(load_config(CONFIG_PATH).sampling.prompt_languages) * load_config(CONFIG_PATH).sampling.round1_samples
        summary = _extract_metrics(run_dir, expected_records)
        summary.model = model
        summary.concurrency = concurrency
        return summary
    except Exception as exc:  # noqa: BLE001
        note = str(exc)
        if run_dir is None:
            run_dir = run_root
        raw_count = len(_read_jsonl(run_dir / "raw_generations.jsonl")) if (run_dir / "raw_generations.jsonl").exists() else 0
        return ProbeRunSummary(
            model=model,
            concurrency=concurrency,
            status="failed",
            note=note,
            run_dir=str(run_dir),
            expected_records=len(item_ids) * len(load_config(CONFIG_PATH).sampling.prompt_languages) * load_config(CONFIG_PATH).sampling.round1_samples,
            raw_record_count=raw_count,
            provider_errors=0,
            empty_responses=0,
            thinking_pollution=0,
            truncation_count=0,
            retry_record_count=0,
            avg_latency_seconds=None,
            max_latency_seconds=None,
            unresolved_count=None,
            round2_candidate_count=None,
            cross_lingual_round1_jsd=None,
            cross_lingual_round1_top1=None,
            human_alignment_en_round1_jsd=None,
            human_alignment_zh_round1_jsd=None,
            sample_answers=[],
        )
    finally:
        _restore_env(previous)
        _ = time.monotonic() - start


def _write_report(
    batch_tag: str,
    item_snapshot_id: str,
    item_ids: list[str],
    model_pool: list[str],
    concurrency_levels: list[int],
    probe_runs: list[ProbeRunSummary],
    model_summaries: list[ModelSummary],
) -> tuple[Path, Path]:
    json_path = RESULTS_ROOT / f"model_stability_probe_{batch_tag}.json"
    md_path = RESULTS_ROOT / f"model_stability_probe_{batch_tag}.md"

    payload = {
        "batch_tag": batch_tag,
        "config_path": str(CONFIG_PATH),
        "item_snapshot_id": item_snapshot_id,
        "item_ids": item_ids,
        "item_count": len(item_ids),
        "concurrency_levels": concurrency_levels,
        "model_pool": model_pool,
        "probe_runs": [asdict(row) for row in probe_runs],
        "model_summaries": [asdict(row) for row in model_summaries],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# Model Stability Probe {batch_tag}",
        "",
        f"- Item snapshot: `{item_snapshot_id}`",
        f"- Item count per model: `{len(item_ids)}`",
        f"- Concurrency ladder: `{', '.join(str(v) for v in concurrency_levels)}`",
        f"- Model pool size: `{len(model_pool)}`",
        "",
        "## Model Summary",
        "",
        "| Model | Tested Concurrency | Stable Concurrency | Recommended | Status | Notes |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in model_summaries:
        tested = ", ".join(str(v) for v in row.tested_concurrencies) or "-"
        stable = ", ".join(str(v) for v in row.stable_concurrencies) or "-"
        recommended = str(row.recommended_concurrency) if row.recommended_concurrency is not None else "none"
        lines.append(
            f"| {row.model} | {tested} | {stable} | {recommended} | {row.status} | {row.note or '-'} |"
        )

    lines.extend(
        [
            "",
            "## Run Details",
            "",
            "| Model | C | Status | Raw | Expected | Provider Err | Empty | Thinking | Trunc | Avg Latency | Max Latency | Unresolved | JSD R1 | Top1 R1 | EN JSD | ZH JSD | Note |",
            "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in probe_runs:
        lines.append(
            f"| {row.model} | {row.concurrency} | {row.status} | {row.raw_record_count} | {row.expected_records} | "
            f"{row.provider_errors} | {row.empty_responses} | {row.thinking_pollution} | {row.truncation_count} | "
            f"{row.avg_latency_seconds if row.avg_latency_seconds is not None else ''} | "
            f"{row.max_latency_seconds if row.max_latency_seconds is not None else ''} | "
            f"{row.unresolved_count if row.unresolved_count is not None else ''} | "
            f"{row.cross_lingual_round1_jsd if row.cross_lingual_round1_jsd is not None else ''} | "
            f"{row.cross_lingual_round1_top1 if row.cross_lingual_round1_top1 is not None else ''} | "
            f"{row.human_alignment_en_round1_jsd if row.human_alignment_en_round1_jsd is not None else ''} | "
            f"{row.human_alignment_zh_round1_jsd if row.human_alignment_zh_round1_jsd is not None else ''} | "
            f"{row.note or '-'} |"
        )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> int:
    _load_env()
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)

    parser = argparse.ArgumentParser(description="Run a 5-example stability probe across the current API model pool.")
    parser.add_argument("--item-count", type=int, default=DEFAULT_ITEM_COUNT)
    parser.add_argument(
        "--concurrency-levels",
        default=",".join(str(value) for value in DEFAULT_CONCURRENCY_LEVELS),
        help="Comma-separated concurrency ladder, e.g. 1,2,4",
    )
    parser.add_argument(
        "--models",
        default="",
        help="Optional comma-separated subset of models to probe. Default: fetch all from the current API key.",
    )
    args = parser.parse_args()

    config = load_config(CONFIG_PATH)
    prepared_snapshot_id, item_ids = _load_probe_item_ids(args.item_count)
    if len(item_ids) < args.item_count:
        raise RuntimeError(f"Requested {args.item_count} items, but only found {len(item_ids)} for the panel.")

    model_pool = _model_pool()
    if args.models.strip():
        wanted = [value.strip() for value in args.models.split(",") if value.strip()]
        model_pool = [model for model in model_pool if model in wanted]

    concurrency_levels = [int(value.strip()) for value in args.concurrency_levels.split(",") if value.strip()]
    batch_tag = datetime.now().strftime("%Y%m%dT%H%M%SZ")

    print(f"[probe] snapshot={prepared_snapshot_id} items={len(item_ids)}", flush=True)
    print(f"[probe] models={', '.join(model_pool)}", flush=True)
    print(f"[probe] concurrencies={', '.join(str(value) for value in concurrency_levels)}", flush=True)

    probe_runs: list[ProbeRunSummary] = []
    model_summaries: list[ModelSummary] = []

    expected_records = len(item_ids) * len(config.sampling.prompt_languages) * config.sampling.round1_samples
    for model in model_pool:
        tested: list[int] = []
        stable: list[int] = []
        best_run_dir = ""
        note = ""
        print(f"[model] {model}", flush=True)
        for concurrency in concurrency_levels:
            tested.append(concurrency)
            print(f"  [run] c={concurrency}", flush=True)
            run_summary = _run_probe(
                model=model,
                concurrency=concurrency,
                batch_tag=batch_tag,
                item_ids=item_ids,
            )
            if not run_summary.expected_records:
                run_summary.expected_records = expected_records
            probe_runs.append(run_summary)
            print(
                f"  [done] status={run_summary.status} raw={run_summary.raw_record_count} "
                f"provider={run_summary.provider_errors} empty={run_summary.empty_responses} "
                f"thinking={run_summary.thinking_pollution} trunc={run_summary.truncation_count}",
                flush=True,
            )
            if run_summary.status == "stable":
                stable.append(concurrency)
                best_run_dir = run_summary.run_dir
                note = "ok"
                continue
            note = run_summary.note
            break

        recommended = stable[-1] if stable else None
        model_status = "stable" if stable else "unstable"
        model_summaries.append(
            ModelSummary(
                model=model,
                tested_concurrencies=tested,
                stable_concurrencies=stable,
                recommended_concurrency=recommended,
                status=model_status,
                note=note,
                best_run_dir=best_run_dir,
            )
        )

        json_path, md_path = _write_report(
            batch_tag=batch_tag,
            item_snapshot_id=prepared_snapshot_id,
            item_ids=item_ids,
            model_pool=model_pool,
            concurrency_levels=concurrency_levels,
            probe_runs=probe_runs,
            model_summaries=model_summaries,
        )
        print(f"partial_json={json_path}", flush=True)
        print(f"partial_md={md_path}", flush=True)

    json_path, md_path = _write_report(
        batch_tag=batch_tag,
        item_snapshot_id=prepared_snapshot_id,
        item_ids=item_ids,
        model_pool=model_pool,
        concurrency_levels=concurrency_levels,
        probe_runs=probe_runs,
        model_summaries=model_summaries,
    )
    print(f"report_json={json_path}", flush=True)
    print(f"report_md={md_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
