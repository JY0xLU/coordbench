from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "full_experiments"
RESULTS_ROOT = REPO_ROOT / "results"
FULL_EXPERIMENT_RESULTS_ROOT = RESULTS_ROOT / "full_experiments"
INDEX_ROOT = FULL_EXPERIMENT_RESULTS_ROOT / "indexes"
SUMMARY_ROOT = FULL_EXPERIMENT_RESULTS_ROOT / "summaries"
INDEX_BASENAME = "new_models_full_experiments"
USAGE_API_BASE = os.environ.get("TOKENLAND_API_BASE", "https://api.mytokenland.com").rstrip("/")
POLL_SECONDS = 60

# Ordered from cheaper / less risky to more expensive, matching the probe + quota review.
MODELS: list[tuple[str, int]] = [
    ("gemini-3.1-flash", 1),
    ("gemini-3.1-flash-lite", 1),
    ("glm-5", 4),
    ("kimi-for-coding", 1),
    ("gemini-3.1-pro", 4),
    ("gpt-5.4-mini", 4),
    ("claude-sonnet-4-6", 1),
    ("gpt-5.4", 4),
    ("mimo-v2-omni", 4),
    ("gpt-5.3-codex", 4),
    ("claude-opus-4-6", 4),
]

INFRASTRUCTURE_MARKERS = (
    "503",
    "504",
    "dns",
    "ssl",
    "connection reset",
    "read timed out",
    "name resolution",
    "failed to resolve",
    "bad gateway",
    "service unavailable",
)
THINKING_MARKERS = ("thinking process", "<think>", "reasoning:", "analysis:", "let's think", "i think")

_REQUESTS_SESSION = requests.Session()
_REQUESTS_SESSION.trust_env = False


@dataclass
class UsageSnapshot:
    total_granted: int | None
    total_used: int | None
    total_available: int | None
    name: str | None = None
    unlimited_quota: bool | None = None


@dataclass
class LogSnapshot:
    model: str
    created_at: int | None
    quota: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    use_time: int | None
    model_ratio: int | None
    completion_ratio: int | None
    group_ratio: int | None
    cache_ratio: int | None
    billing_source: str | None
    usage_semantic: str | None
    request_path: str | None


@dataclass
class ModelRunIndex:
    model: str
    concurrency: int
    root_tag: str
    status: str
    stop_reason: str
    run_dir: str
    raw_count: int
    provider_errors: int
    empty_responses: int
    thinking_pollution: int
    truncation_count: int
    usage_total_used_before: int | None
    usage_total_used_after: int | None
    quota_delta: int | None
    usage_total_available_before: int | None
    usage_total_available_after: int | None
    latest_log_quota: int | None
    latest_model_ratio: int | None
    latest_completion_ratio: int | None
    latest_group_ratio: int | None
    latest_cache_ratio: int | None
    latest_billing_source: str | None
    latest_usage_semantic: str | None
    latest_request_path: str | None
    latest_prompt_tokens: int | None
    latest_completion_tokens: int | None
    summary_json: str
    summary_md: str


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


def _safe_name(name: str) -> str:
    return name.replace("/", "__").replace(" ", "_")


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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


def _usage_headers() -> dict[str, str]:
    key = str(os.environ.get("UNIVERSAL_API_KEY", "")).strip()
    return {"Authorization": f"Bearer {key}"} if key else {}


def _fetch_usage_snapshot() -> UsageSnapshot | None:
    headers = _usage_headers()
    if not headers:
        return None
    try:
        response = _REQUESTS_SESSION.get(f"{USAGE_API_BASE}/api/usage/token/", headers=headers, timeout=30)
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return None
        return UsageSnapshot(
            total_granted=_to_int(data.get("total_granted")),
            total_used=_to_int(data.get("total_used")),
            total_available=_to_int(data.get("total_available")),
            name=str(data.get("name")) if data.get("name") is not None else None,
            unlimited_quota=bool(data.get("unlimited_quota")) if data.get("unlimited_quota") is not None else None,
        )
    except Exception:
        return None


def _parse_other_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _fetch_latest_log_snapshot(model: str, since_epoch: float | None = None) -> LogSnapshot | None:
    headers = _usage_headers()
    if not headers:
        return None
    try:
        response = _REQUESTS_SESSION.get(f"{USAGE_API_BASE}/api/log/token", headers=headers, timeout=30)
        response.raise_for_status()
        payload = response.json()
        items = payload.get("data") if isinstance(payload, dict) else payload
        if isinstance(items, dict):
            items = items.get("items") or items.get("logs") or items.get("data")
        if not isinstance(items, list):
            return None

        since_cutoff = int(since_epoch or 0) - 120 if since_epoch else None
        candidates: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("model_name") or "") != model:
                continue
            created_at = _to_int(item.get("created_at")) or 0
            if since_cutoff is not None and created_at < since_cutoff:
                continue
            candidates.append(item)

        if not candidates:
            for item in items:
                if not isinstance(item, dict):
                    continue
                if str(item.get("model_name") or "") == model:
                    candidates.append(item)

        if not candidates:
            return None

        latest = max(
            candidates,
            key=lambda item: (_to_int(item.get("created_at")) or 0, _to_int(item.get("id")) or 0),
        )
        other = _parse_other_payload(latest.get("other"))
        return LogSnapshot(
            model=model,
            created_at=_to_int(latest.get("created_at")),
            quota=_to_int(latest.get("quota")),
            prompt_tokens=_to_int(latest.get("prompt_tokens")),
            completion_tokens=_to_int(latest.get("completion_tokens")),
            use_time=_to_int(latest.get("use_time")),
            model_ratio=_to_int(other.get("model_ratio")),
            completion_ratio=_to_int(other.get("completion_ratio")),
            group_ratio=_to_int(other.get("group_ratio")),
            cache_ratio=_to_int(other.get("cache_ratio")),
            billing_source=str(other.get("billing_source")) if other.get("billing_source") is not None else None,
            usage_semantic=str(other.get("usage_semantic")) if other.get("usage_semantic") is not None else None,
            request_path=str(other.get("request_path")) if other.get("request_path") is not None else None,
        )
    except Exception:
        return None


def _looks_like_thinking(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in THINKING_MARKERS)


def _find_run_dir(root_tag: str, model: str) -> Path | None:
    runs_root = ARTIFACT_ROOT / root_tag / _safe_name(model) / "runs"
    if not runs_root.exists():
        return None
    run_dirs = sorted(path for path in runs_root.iterdir() if path.is_dir())
    return run_dirs[-1] if run_dirs else None


def _metrics_for_run(run_dir: Path | None) -> dict[str, int]:
    if run_dir is None:
        return {
            "raw_count": 0,
            "provider_errors": 0,
            "empty_responses": 0,
            "thinking_pollution": 0,
            "truncation_count": 0,
        }
    rows = _read_jsonl(run_dir / "raw_generations.jsonl")
    provider_errors = 0
    empty_responses = 0
    thinking_pollution = 0
    truncation_count = 0
    for row in rows:
        text = str(row.get("response_text", "") or "")
        lowered = text.lower()
        if str(row.get("response_source", "") or "") == "provider_error" or str(row.get("error", "") or ""):
            provider_errors += 1
        if not text.strip():
            empty_responses += 1
        if any(marker in lowered for marker in THINKING_MARKERS):
            thinking_pollution += 1
        if str(row.get("finish_reason", "") or "").lower() in {"length", "max_tokens"}:
            truncation_count += 1
    return {
        "raw_count": len(rows),
        "provider_errors": provider_errors,
        "empty_responses": empty_responses,
        "thinking_pollution": thinking_pollution,
        "truncation_count": truncation_count,
    }


def _failure_lines(err_log: Path) -> list[str]:
    if not err_log.exists():
        return []
    return [
        line.strip()
        for line in err_log.read_text(encoding="utf-8", errors="replace").splitlines()
        if "Provider openai failed" in line
    ]


def _infrastructure_failure_count(err_log: Path) -> int:
    count = 0
    for line in _failure_lines(err_log):
        lowered = line.lower()
        if any(marker in lowered for marker in INFRASTRUCTURE_MARKERS):
            count += 1
    return count


def _terminate_process(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _index_paths(batch_tag: str) -> tuple[Path, Path]:
    json_path = INDEX_ROOT / f"{INDEX_BASENAME}_{batch_tag}.json"
    md_path = INDEX_ROOT / f"{INDEX_BASENAME}_{batch_tag}.md"
    return json_path, md_path


def _ratio_text(snapshot: LogSnapshot | None) -> str:
    if snapshot is None:
        return "-"
    return (
        f"m={snapshot.model_ratio if snapshot.model_ratio is not None else '-'}"
        f"/c={snapshot.completion_ratio if snapshot.completion_ratio is not None else '-'}"
        f"/g={snapshot.group_ratio if snapshot.group_ratio is not None else '-'}"
        f"/cache={snapshot.cache_ratio if snapshot.cache_ratio is not None else '-'}"
    )


def _write_index(batch_tag: str, rows: list[ModelRunIndex]) -> tuple[Path, Path]:
    json_path, md_path = _index_paths(batch_tag)
    json_path.write_text(json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# New Models Full Experiments {batch_tag}",
        "",
        "| Model | Concurrency | Status | Stop Reason | Raw | Provider Errors | Empty | Thinking | Truncation | Quota Δ | Used Before | Used After | Last Ratios | Last Log Quota | Run Dir |",
        "| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row.model} | {row.concurrency} | {row.status} | {row.stop_reason or 'completed'} | "
            f"{row.raw_count} | {row.provider_errors} | {row.empty_responses} | "
            f"{row.thinking_pollution} | {row.truncation_count} | "
            f"{row.quota_delta if row.quota_delta is not None else ''} | "
            f"{row.usage_total_used_before if row.usage_total_used_before is not None else ''} | "
            f"{row.usage_total_used_after if row.usage_total_used_after is not None else ''} | "
            f"{_ratio_text(LogSnapshot(
                model=row.model,
                created_at=None,
                quota=row.latest_log_quota,
                prompt_tokens=row.latest_prompt_tokens,
                completion_tokens=row.latest_completion_tokens,
                use_time=None,
                model_ratio=row.latest_model_ratio,
                completion_ratio=row.latest_completion_ratio,
                group_ratio=row.latest_group_ratio,
                cache_ratio=row.latest_cache_ratio,
                billing_source=row.latest_billing_source,
                usage_semantic=row.latest_usage_semantic,
                request_path=row.latest_request_path,
            ))} | "
            f"{row.latest_log_quota if row.latest_log_quota is not None else ''} | "
            f"`{row.run_dir}` |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def _start_model(model: str, concurrency: int, root_tag: str, out_log: Path, err_log: Path) -> subprocess.Popen[str]:
    args = [
        sys.executable,
        "scripts/run_one_full_experiment.py",
        "--model",
        model,
        "--concurrency",
        str(concurrency),
        "--root-tag",
        root_tag,
    ]
    return subprocess.Popen(
        args,
        cwd=REPO_ROOT,
        stdout=out_log.open("w", encoding="utf-8"),
        stderr=err_log.open("w", encoding="utf-8"),
        text=True,
    )


def main() -> int:
    _load_env()
    INDEX_ROOT.mkdir(parents=True, exist_ok=True)
    SUMMARY_ROOT.mkdir(parents=True, exist_ok=True)
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)

    batch_tag = datetime.now().strftime("%Y%m%dT%H%M%SZ")
    index_rows: list[ModelRunIndex] = []

    for model, concurrency in MODELS:
        safe_name = _safe_name(model)
        root_tag = f"{batch_tag}_{safe_name}_c{concurrency}"
        out_log = ARTIFACT_ROOT / f"{root_tag}.out.log"
        err_log = ARTIFACT_ROOT / f"{root_tag}.err.log"

        print(f"[run] model={model} concurrency={concurrency}", flush=True)
        usage_before = _fetch_usage_snapshot()
        if usage_before is not None:
            print(
                f"[usage-before] used={usage_before.total_used} available={usage_before.total_available}",
                flush=True,
            )

        proc = _start_model(model, concurrency, root_tag, out_log, err_log)
        started_at_monotonic = time.monotonic()
        started_at_wall = time.time()
        previous_raw_count = -1
        stable_polls_without_growth = 0
        stop_reason = ""

        while proc.poll() is None:
            time.sleep(POLL_SECONDS)
            run_dir = _find_run_dir(root_tag, model)
            metrics = _metrics_for_run(run_dir)
            raw_count = metrics["raw_count"]
            failure_count = len(_failure_lines(err_log))
            infra_failure_count = _infrastructure_failure_count(err_log)
            elapsed = time.monotonic() - started_at_monotonic

            if raw_count == previous_raw_count:
                stable_polls_without_growth += 1
            else:
                stable_polls_without_growth = 0
                previous_raw_count = raw_count

            if elapsed >= 180 and raw_count == 0 and failure_count >= 12:
                stop_reason = "no_raw_after_3m_and_failures>=12"
            elif elapsed >= 300 and raw_count < 20 and failure_count >= 25:
                stop_reason = "raw_lt_20_after_5m_and_failures>=25"
            elif raw_count > 0 and metrics["provider_errors"] / raw_count > 0.20:
                stop_reason = "provider_error_ratio_gt_20pct"
            elif raw_count > 0 and metrics["empty_responses"] / raw_count > 0.20:
                stop_reason = "empty_response_ratio_gt_20pct"
            elif raw_count > 0 and metrics["truncation_count"] / raw_count > 0.20:
                stop_reason = "truncation_ratio_gt_20pct"
            elif metrics["thinking_pollution"] > 0:
                stop_reason = "thinking_pollution_detected"
            elif infra_failure_count >= 10 and stable_polls_without_growth >= 1:
                stop_reason = "infrastructure_failures_with_stalled_raw_growth"

            if stop_reason:
                print(f"[early-stop] model={model} reason={stop_reason}", flush=True)
                _terminate_process(proc)
                break

        run_dir = _find_run_dir(root_tag, model)
        metrics = _metrics_for_run(run_dir)
        summary_json = ARTIFACT_ROOT / root_tag / "summary.json"
        summary_md = SUMMARY_ROOT / f"full_experiment_summary_{root_tag}.md"
        if stop_reason:
            status = "stopped_early"
        else:
            status = "completed" if summary_json.exists() else "failed"

        usage_after = _fetch_usage_snapshot()
        if usage_after is not None:
            print(
                f"[usage-after] used={usage_after.total_used} available={usage_after.total_available}",
                flush=True,
            )
        latest_log = _fetch_latest_log_snapshot(model, since_epoch=started_at_wall)
        if latest_log is not None:
            print(
                "[log-audit] "
                f"quota={latest_log.quota} ratios={_ratio_text(latest_log)} "
                f"semantic={latest_log.usage_semantic or '-'} path={latest_log.request_path or '-'}",
                flush=True,
            )

        quota_delta = None
        if usage_before is not None and usage_after is not None:
            quota_delta = None
            if usage_before.total_used is not None and usage_after.total_used is not None:
                quota_delta = usage_after.total_used - usage_before.total_used

        index_rows.append(
            ModelRunIndex(
                model=model,
                concurrency=concurrency,
                root_tag=root_tag,
                status=status,
                stop_reason=stop_reason,
                run_dir="" if run_dir is None else str(run_dir),
                raw_count=metrics["raw_count"],
                provider_errors=metrics["provider_errors"],
                empty_responses=metrics["empty_responses"],
                thinking_pollution=metrics["thinking_pollution"],
                truncation_count=metrics["truncation_count"],
                usage_total_used_before=usage_before.total_used if usage_before is not None else None,
                usage_total_used_after=usage_after.total_used if usage_after is not None else None,
                quota_delta=quota_delta,
                usage_total_available_before=usage_before.total_available if usage_before is not None else None,
                usage_total_available_after=usage_after.total_available if usage_after is not None else None,
                latest_log_quota=latest_log.quota if latest_log is not None else None,
                latest_model_ratio=latest_log.model_ratio if latest_log is not None else None,
                latest_completion_ratio=latest_log.completion_ratio if latest_log is not None else None,
                latest_group_ratio=latest_log.group_ratio if latest_log is not None else None,
                latest_cache_ratio=latest_log.cache_ratio if latest_log is not None else None,
                latest_billing_source=latest_log.billing_source if latest_log is not None else None,
                latest_usage_semantic=latest_log.usage_semantic if latest_log is not None else None,
                latest_request_path=latest_log.request_path if latest_log is not None else None,
                latest_prompt_tokens=latest_log.prompt_tokens if latest_log is not None else None,
                latest_completion_tokens=latest_log.completion_tokens if latest_log is not None else None,
                summary_json=str(summary_json) if summary_json.exists() else "",
                summary_md=str(summary_md) if summary_md.exists() else "",
            )
        )
        _write_index(batch_tag, index_rows)

    json_path, md_path = _write_index(batch_tag, index_rows)
    print(f"index_json={json_path}", flush=True)
    print(f"index_md={md_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
