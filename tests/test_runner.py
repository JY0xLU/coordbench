import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from coordbench.cache import cache_key_for_request, cache_path
from coordbench.models import GenerationRequest, GenerationResponse
from coordbench.runner import run_sampling


def _write_runner_config(tmp_path: Path, *, round1_samples: int = 2) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "providers:",
                "  mock:",
                "    enabled: true",
                "    model: mock-v1",
                "    api_key_env: ''",
                "    concurrency: 1",
                "    max_retries: 1",
                "    temperature: 1.0",
                "    max_output_tokens: 8",
                "sampling:",
                "  panel_id: study2_british_within",
                "  answer_language: English",
                "  prompt_languages: [en]",
                f"  round1_samples: {round1_samples}",
                "  round2_samples: 1",
                "  enable_round2: false",
                "  round2_trigger: cross_lingual_top1_mismatch",
                "  random_seed: 1",
                "normalization:",
                f"  alias_path: {tmp_path.as_posix()}/aliases.csv",
                "  allow_unmapped: true",
                "  fuzzy_match_threshold: 95",
                "analysis:",
                "  bootstrap_resamples: 10",
                "  item_bootstrap_resamples: 10",
                "outputs:",
                f"  run_root: {tmp_path.as_posix()}/runs",
                f"  cache_root: {tmp_path.as_posix()}/cache",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "aliases.csv").write_text("panel_id,item_id,surface_form,canonical_answer,notes\n", encoding="utf-8")
    return config_path


def _write_panel_items(snapshot_dir: Path, *, item_text: str) -> None:
    snapshot_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "panel_id": "study2_british_within",
                "study_id": "study2",
                "respondent_group": "british",
                "target_group": "british",
                "relation": "within",
                "item_id": "study2_item_01",
                "item_number": 1,
                "item_text_en": item_text,
                "item_text_zh": "city zh",
            }
        ]
    ).to_csv(snapshot_dir / "panel_items.csv", index=False)


def test_run_sampling_resumes_without_duplicate_rows_and_keeps_bound_snapshot(tmp_path: Path, monkeypatch):
    prepared_root = tmp_path / "prepared"
    first_snapshot = prepared_root / "snapshot_a"
    second_snapshot = prepared_root / "snapshot_b"
    _write_panel_items(first_snapshot, item_text="Name a city")
    _write_panel_items(second_snapshot, item_text="Different item text")

    config_path = _write_runner_config(tmp_path)
    run_dir = tmp_path / "runs" / "resume-run"

    monkeypatch.setattr("coordbench.runner.latest_prepared_snapshot_or_raise", lambda: first_snapshot)
    monkeypatch.setattr("coordbench.run_state.prepared_root", lambda: prepared_root)

    run_sampling(config_path, run_dir=run_dir)
    first_rows = [json.loads(line) for line in (run_dir / "raw_generations.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(first_rows) == 2

    monkeypatch.setattr("coordbench.runner.latest_prepared_snapshot_or_raise", lambda: second_snapshot)
    run_sampling(config_path, run_dir=run_dir)

    second_rows = [json.loads(line) for line in (run_dir / "raw_generations.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(second_rows) == 2
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["prepared_snapshot_id"] == "snapshot_a"


def test_run_sampling_retries_records_with_invalid_response_text(tmp_path: Path, monkeypatch):
    prepared_root = tmp_path / "prepared"
    snapshot = prepared_root / "snapshot_a"
    _write_panel_items(snapshot, item_text="Name a city")

    config_path = _write_runner_config(tmp_path, round1_samples=1)
    run_dir = tmp_path / "runs" / "retry-run"
    run_dir.mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"run_id": "retry-run", "prepared_snapshot_id": "snapshot_a", "panel_id": "study2_british_within"}),
        encoding="utf-8",
    )
    invalid_row = {
        "provider": "mock",
        "model": "mock-v1",
        "requested_model": "mock-v1",
        "resolved_model": "mock-v1",
        "provider_backend": "mock",
        "panel_id": "study2_british_within",
        "item_id": "study2_item_01",
        "item_text_en": "Name a city",
        "item_text_zh": "city zh",
        "prompt_language": "en",
        "answer_language": "English",
        "round_index": 1,
        "sample_index": 0,
        "temperature": 1.0,
        "max_output_tokens": 8,
        "seed": 2,
        "provider_timeout_seconds": 120,
        "provider_concurrency": 1,
        "request_cache_key": "invalid-cache-key",
        "system_prompt": "system",
        "user_prompt": "user",
        "response_text": "Thinking Process:\n\n1. Analyze the request.",
        "finish_reason": None,
        "request_id": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "latency_seconds": 0.0,
        "response_source": "provider_api",
        "retry_count": 0,
        "attempt_count": 1,
        "cache_hit": False,
        "disk_cache_hit": False,
        "provider_cached_tokens": None,
        "error": None,
        "raw_payload": {},
        "generated_at_utc": "2026-03-24T00:00:00Z",
    }
    with (run_dir / "raw_generations.jsonl").open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(invalid_row, ensure_ascii=False) + "\n")

    monkeypatch.setattr("coordbench.runner.latest_prepared_snapshot_or_raise", lambda: snapshot)
    monkeypatch.setattr("coordbench.run_state.prepared_root", lambda: prepared_root)

    run_sampling(config_path, run_dir=run_dir)

    rows = [json.loads(line) for line in (run_dir / "raw_generations.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[-1]["response_source"] == "provider_api"
    assert rows[-1]["response_text"] != invalid_row["response_text"]


def test_run_sampling_ignores_invalid_cached_responses(tmp_path: Path, monkeypatch):
    prepared_root = tmp_path / "prepared"
    snapshot = prepared_root / "snapshot_a"
    _write_panel_items(snapshot, item_text="Name a city")

    config_path = _write_runner_config(tmp_path, round1_samples=1)
    monkeypatch.setattr("coordbench.runner.latest_prepared_snapshot_or_raise", lambda: snapshot)
    monkeypatch.setattr("coordbench.run_state.prepared_root", lambda: prepared_root)

    request = GenerationRequest(
        provider="mock",
        model="mock-v1",
        panel_id="study2_british_within",
        item_id="study2_item_01",
        item_text_en="Name a city",
        item_text_zh="city zh",
        prompt_language="en",
        answer_language="English",
        round_index=1,
        sample_index=0,
        system_prompt="Return one answer only.",
        user_prompt="Category: Name a city",
        temperature=1.0,
        max_output_tokens=8,
        seed=2,
    )
    invalid_cached = GenerationResponse(
        provider="mock",
        model="mock-v1",
        text="Thinking Process:\n\n1. Analyze the request.",
        raw_payload={"mock": True},
        finish_reason=None,
        request_id="mock-invalid",
        latency_seconds=0.0,
    )
    invalid_cache_path = cache_path(tmp_path / "cache", "mock", "mock-v1", cache_key_for_request(request))
    invalid_cache_path.parent.mkdir(parents=True, exist_ok=True)
    invalid_cache_path.write_text(json.dumps(asdict(invalid_cached)), encoding="utf-8")

    run_dir = run_sampling(config_path, round_index=1)
    rows = [json.loads(line) for line in (run_dir / "raw_generations.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["response_source"] == "provider_api"
