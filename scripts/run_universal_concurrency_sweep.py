from __future__ import annotations

import json
import os
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from coordbench.runner import run_sampling


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "configs" / "universal_api_openai.yaml"
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "sweeps"
RESULTS_ROOT = REPO_ROOT / "results" / "concurrency_sweeps"

PHASE1_CONCURRENCY = [2, 4, 6]
PHASE2_CONCURRENCY = [8, 10]

MODEL_PRICE_TIERS = {
    "claude-sonnet-4-6": "1x",
    "gpt-5.4-mini": "2x",
    "MiniMax-M2.7-highspeed": "1x",
    "MiniMax-M2.7": "1x",
    "qwen3.5-plus": "1x",
    "qwen3-coder-plus": "1x",
    "glm-5": "unknown",
    "step-3.5-flash": "unknown",
    "kimi-for-coding": "2x",
}

MODELS = [
    "claude-sonnet-4-6",
    "gpt-5.4-mini",
    "MiniMax-M2.7-highspeed",
    "MiniMax-M2.7",
    "qwen3.5-plus",
    "qwen3-coder-plus",
    "glm-5",
    "step-3.5-flash",
    "kimi-for-coding",
]


@dataclass
class RunSummary:
    model: str
    price_tier: str
    concurrency: int
    phase: str
    run_dir: str
    wall_seconds: float
    total_records: int
    success_count: int
    provider_error_count: int
    empty_response_count: int
    thought_pollution_count: int
    truncation_count: int
    retry_record_count: int
    max_retry_count: int
    avg_latency_seconds: float | None
    max_latency_seconds: float | None
    anomalous_items: dict[str, int]
    anomalous_languages: dict[str, int]
    sample_answers: list[str]
    stable: bool
    verdict: str


def _safe_name(name: str) -> str:
    return name.replace("/", "__").replace(" ", "_")


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
    markers = [
        "thinking process",
        "<think>",
        "reasoning:",
        "analysis:",
        "let's think",
        "i think",
    ]
    return any(marker in lowered for marker in markers)


def _word_count(text: str) -> int:
    return len([part for part in text.replace("\n", " ").split(" ") if part.strip()])


def _summarize_run(
    *,
    model: str,
    concurrency: int,
    phase: str,
    run_dir: Path,
    wall_seconds: float,
) -> RunSummary:
    raw_path = run_dir / "raw_generations.jsonl"
    rows = _read_jsonl(raw_path)

    success_rows: list[dict[str, Any]] = []
    provider_error_count = 0
    empty_response_count = 0
    thought_pollution_count = 0
    truncation_count = 0
    retry_record_count = 0
    max_retry_count = 0
    latencies: list[float] = []
    anomalous_items: Counter[str] = Counter()
    anomalous_languages: Counter[str] = Counter()
    sample_answers: list[str] = []

    for row in rows:
        text = str(row.get("response_text", "") or "")
        error = str(row.get("error", "") or "")
        source = str(row.get("response_source", "") or "")
        finish_reason = str(row.get("finish_reason", "") or "").lower()
        retry_count = int(row.get("retry_count", 0) or 0)
        item_id = str(row.get("item_id", "") or "")
        prompt_language = str(row.get("prompt_language", "") or "")

        if retry_count > 0:
            retry_record_count += 1
            max_retry_count = max(max_retry_count, retry_count)

        latency = row.get("latency_seconds")
        if latency is not None:
            latencies.append(float(latency))

        is_provider_error = source == "provider_error" or bool(error)
        is_empty = not text.strip()
        is_thinking = _looks_like_thinking(text)
        is_truncated = finish_reason in {"length", "max_tokens"}

        if is_provider_error:
            provider_error_count += 1
            anomalous_items[item_id] += 1
            anomalous_languages[prompt_language] += 1
        if is_empty:
            empty_response_count += 1
            anomalous_items[item_id] += 1
            anomalous_languages[prompt_language] += 1
        if is_thinking:
            thought_pollution_count += 1
            anomalous_items[item_id] += 1
            anomalous_languages[prompt_language] += 1
        if is_truncated:
            truncation_count += 1
            anomalous_items[item_id] += 1
            anomalous_languages[prompt_language] += 1

        if not (is_provider_error or is_empty or is_thinking or is_truncated):
            success_rows.append(row)
            if len(sample_answers) < 5:
                sample_answers.append(text)

    stable = (
        len(rows) == 30
        and provider_error_count == 0
        and empty_response_count == 0
        and thought_pollution_count == 0
        and truncation_count == 0
        and retry_record_count <= 2
    )

    if stable:
        verdict = "stable"
    elif success_rows and provider_error_count <= 2 and thought_pollution_count == 0:
        verdict = "usable_with_caution"
    else:
        verdict = "unstable"

    return RunSummary(
        model=model,
        price_tier=MODEL_PRICE_TIERS.get(model, "unknown"),
        concurrency=concurrency,
        phase=phase,
        run_dir=str(run_dir),
        wall_seconds=round(wall_seconds, 2),
        total_records=len(rows),
        success_count=len(success_rows),
        provider_error_count=provider_error_count,
        empty_response_count=empty_response_count,
        thought_pollution_count=thought_pollution_count,
        truncation_count=truncation_count,
        retry_record_count=retry_record_count,
        max_retry_count=max_retry_count,
        avg_latency_seconds=round(statistics.mean(latencies), 2) if latencies else None,
        max_latency_seconds=round(max(latencies), 2) if latencies else None,
        anomalous_items=dict(anomalous_items),
        anomalous_languages=dict(anomalous_languages),
        sample_answers=sample_answers,
        stable=stable,
        verdict=verdict,
    )


def _run_one(
    sweep_dir: Path,
    model: str,
    concurrency: int,
    phase: str,
) -> RunSummary:
    safe_model = _safe_name(model)
    run_root = sweep_dir / "runs" / safe_model / f"c{concurrency}"
    cache_root = sweep_dir / "cache" / safe_model / f"c{concurrency}"
    run_root.mkdir(parents=True, exist_ok=True)
    cache_root.mkdir(parents=True, exist_ok=True)

    old_values = {
        "UNIVERSAL_MODEL": os.environ.get("UNIVERSAL_MODEL"),
        "UNIVERSAL_CONCURRENCY": os.environ.get("UNIVERSAL_CONCURRENCY"),
        "UNIVERSAL_RUN_ROOT": os.environ.get("UNIVERSAL_RUN_ROOT"),
        "UNIVERSAL_CACHE_ROOT": os.environ.get("UNIVERSAL_CACHE_ROOT"),
    }
    os.environ["UNIVERSAL_MODEL"] = model
    os.environ["UNIVERSAL_CONCURRENCY"] = str(concurrency)
    os.environ["UNIVERSAL_RUN_ROOT"] = str(run_root)
    os.environ["UNIVERSAL_CACHE_ROOT"] = str(cache_root)

    try:
        start = time.monotonic()
        created_run_dir = run_sampling(CONFIG_PATH, round_index=1)
        wall_seconds = time.monotonic() - start
    finally:
        for key, value in old_values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    return _summarize_run(
        model=model,
        concurrency=concurrency,
        phase=phase,
        run_dir=Path(created_run_dir),
        wall_seconds=wall_seconds,
    )


def _load_existing_results(path: Path) -> list[RunSummary]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [RunSummary(**item) for item in payload]


def _save_results(path: Path, rows: list[RunSummary]) -> None:
    payload = [asdict(row) for row in rows]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _existing_lookup(rows: list[RunSummary]) -> set[tuple[str, int, str]]:
    return {(row.model, row.concurrency, row.phase) for row in rows}


def _phase1(rows: list[RunSummary], sweep_dir: Path) -> list[RunSummary]:
    existing = _existing_lookup(rows)
    for model in MODELS:
        model_failed = False
        for concurrency in PHASE1_CONCURRENCY:
            key = (model, concurrency, "phase1")
            if key in existing:
                summary = next(row for row in rows if (row.model, row.concurrency, row.phase) == key)
            else:
                print(f"[phase1] model={model} concurrency={concurrency}", flush=True)
                summary = _run_one(sweep_dir, model, concurrency, "phase1")
                rows.append(summary)
                existing.add(key)
                _save_results(sweep_dir / "results.json", rows)

            if not summary.stable:
                model_failed = True
                break
        if model_failed:
            continue
    return rows


def _stable_at_concurrency(rows: list[RunSummary], model: str, concurrency: int, phase: str) -> bool:
    for row in rows:
        if row.model == model and row.concurrency == concurrency and row.phase == phase:
            return row.stable
    return False


def _phase2(rows: list[RunSummary], sweep_dir: Path) -> list[RunSummary]:
    existing = _existing_lookup(rows)
    candidates = [model for model in MODELS if _stable_at_concurrency(rows, model, 6, "phase1")]
    for model in candidates:
        for concurrency in PHASE2_CONCURRENCY:
            key = (model, concurrency, "phase2")
            if key in existing:
                summary = next(row for row in rows if (row.model, row.concurrency, row.phase) == key)
            else:
                print(f"[phase2] model={model} concurrency={concurrency}", flush=True)
                summary = _run_one(sweep_dir, model, concurrency, "phase2")
                rows.append(summary)
                existing.add(key)
                _save_results(sweep_dir / "results.json", rows)
            if not summary.stable:
                break
    return rows


def _best_runs(rows: list[RunSummary]) -> list[RunSummary]:
    best_by_model: dict[str, RunSummary] = {}
    for row in rows:
        if row.verdict == "unstable":
            continue
        current = best_by_model.get(row.model)
        if current is None:
            best_by_model[row.model] = row
            continue
        current_key = (0 if current.stable else 1, current.price_tier, -current.concurrency, current.wall_seconds)
        row_key = (0 if row.stable else 1, row.price_tier, -row.concurrency, row.wall_seconds)
        if row_key < current_key:
            best_by_model[row.model] = row
    shortlist = sorted(
        best_by_model.values(),
        key=lambda row: (
            0 if row.stable else 1,
            row.price_tier,
            row.wall_seconds,
        ),
    )
    return shortlist[:2]


def _retest(rows: list[RunSummary], sweep_dir: Path) -> list[RunSummary]:
    existing = _existing_lookup(rows)
    for row in _best_runs(rows):
        key = (row.model, row.concurrency, "retest")
        if key in existing:
            continue
        print(f"[retest] model={row.model} concurrency={row.concurrency}", flush=True)
        summary = _run_one(sweep_dir, row.model, row.concurrency, "retest")
        rows.append(summary)
        existing.add(key)
        _save_results(sweep_dir / "results.json", rows)
    return rows


def _model_summary(rows: list[RunSummary]) -> list[dict[str, Any]]:
    grouped: defaultdict[str, list[RunSummary]] = defaultdict(list)
    for row in rows:
        grouped[row.model].append(row)

    summaries: list[dict[str, Any]] = []
    for model, model_rows in grouped.items():
        model_rows = sorted(model_rows, key=lambda row: (row.concurrency, row.phase))
        stable_rows = [row for row in model_rows if row.stable]
        usable_rows = [row for row in model_rows if row.verdict != "unstable"]

        if stable_rows:
            safest = min(stable_rows, key=lambda row: (row.concurrency, row.wall_seconds))
            fastest = min(stable_rows, key=lambda row: row.wall_seconds)
            recommendation = "推荐正式实验"
        elif usable_rows:
            safest = min(usable_rows, key=lambda row: row.wall_seconds)
            fastest = safest
            recommendation = "可用但要保守并发"
        else:
            safest = min(model_rows, key=lambda row: row.wall_seconds)
            fastest = safest
            recommendation = "不建议继续"

        summaries.append(
            {
                "model": model,
                "price_tier": MODEL_PRICE_TIERS.get(model, "unknown"),
                "tested_concurrency": [row.concurrency for row in model_rows if row.phase != "retest"],
                "safest_concurrency": safest.concurrency,
                "fastest_stable_concurrency": fastest.concurrency,
                "best_wall_seconds": fastest.wall_seconds,
                "format_ok": all(
                    row.thought_pollution_count == 0 and row.truncation_count == 0 for row in model_rows
                ),
                "recommendation": recommendation,
                "notes": {
                    "provider_errors": sum(row.provider_error_count for row in model_rows),
                    "empty_responses": sum(row.empty_response_count for row in model_rows),
                    "worst_retry_count": max(row.max_retry_count for row in model_rows),
                },
            }
        )
    return sorted(
        summaries,
        key=lambda item: (
            {"推荐正式实验": 0, "可用但要保守并发": 1, "不建议继续": 2}[item["recommendation"]],
            item["price_tier"],
            item["best_wall_seconds"],
        ),
    )


def _write_report(sweep_dir: Path, rows: list[RunSummary]) -> Path:
    summary_rows = _model_summary(rows)
    report_path = RESULTS_ROOT / f"concurrency_sweep_{sweep_dir.name}.md"

    lines: list[str] = []
    lines.append(f"# Universal API Concurrency Sweep {sweep_dir.name}")
    lines.append("")
    lines.append("## Model Summary")
    lines.append("")
    lines.append("| Model | Price | Tested | Safest | Fastest Stable | Best Wall (s) | Format OK | Recommendation |")
    lines.append("| --- | --- | --- | --- | --- | ---: | --- | --- |")
    for item in summary_rows:
        lines.append(
            f"| {item['model']} | {item['price_tier']} | {', '.join(map(str, item['tested_concurrency']))} | "
            f"{item['safest_concurrency']} | {item['fastest_stable_concurrency']} | {item['best_wall_seconds']:.2f} | "
            f"{'yes' if item['format_ok'] else 'no'} | {item['recommendation']} |"
        )

    lines.append("")
    lines.append("## Detailed Runs")
    lines.append("")
    for row in sorted(rows, key=lambda item: (item.model, item.concurrency, item.phase)):
        lines.append(
            f"- `{row.model}` `c={row.concurrency}` `{row.phase}`: verdict={row.verdict}, "
            f"wall={row.wall_seconds:.2f}s, success={row.success_count}/{row.total_records}, "
            f"errors={row.provider_error_count}, empty={row.empty_response_count}, "
            f"thinking={row.thought_pollution_count}, truncation={row.truncation_count}, "
            f"retry_records={row.retry_record_count}, max_retry={row.max_retry_count}, "
            f"avg_latency={row.avg_latency_seconds if row.avg_latency_seconds is not None else 'n/a'}"
        )
        if row.anomalous_items:
            lines.append(f"  anomalies={row.anomalous_items}")
        if row.sample_answers:
            lines.append(f"  samples={row.sample_answers}")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def main() -> int:
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%SZ")
    sweep_dir = ARTIFACT_ROOT / timestamp
    sweep_dir.mkdir(parents=True, exist_ok=True)
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    results_path = sweep_dir / "results.json"

    rows = _load_existing_results(results_path)
    rows = _phase1(rows, sweep_dir)
    rows = _phase2(rows, sweep_dir)
    rows = _retest(rows, sweep_dir)
    _save_results(results_path, rows)
    report_path = _write_report(sweep_dir, rows)

    print(f"sweep_dir={sweep_dir}")
    print(f"report_path={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
