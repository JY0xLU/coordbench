import json
from pathlib import Path

import pandas as pd

from coordbench.analysis import analyze_run
from coordbench.normalize import normalize_run


def _write_config(
    tmp_path: Path,
    *,
    round1_samples: int = 2,
    round2_trigger: str = "cross_lingual_top1_mismatch",
) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "providers:",
                "  openai:",
                "    enabled: false",
                "    model: ''",
                "    api_key_env: OPENAI_API_KEY",
                "sampling:",
                "  panel_id: study2_british_within",
                "  answer_language: English",
                "  prompt_languages: [en, zh]",
                f"  round1_samples: {round1_samples}",
                "  round2_samples: 1",
                "  enable_round2: true",
                f"  round2_trigger: {round2_trigger}",
                "  random_seed: 1",
                "normalization:",
                f"  alias_path: {tmp_path.as_posix()}/aliases.csv",
                "  allow_unmapped: true",
                "  fuzzy_match_threshold: 95",
                "analysis:",
                "  bootstrap_resamples: 10",
                "  item_bootstrap_resamples: 10",
                "  min_cell_completion_rate: 0.8",
                "outputs:",
                f"  run_root: {tmp_path.as_posix()}/runs",
                f"  cache_root: {tmp_path.as_posix()}/cache",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "aliases.csv").write_text("panel_id,item_id,surface_form,canonical_answer,notes\n", encoding="utf-8")
    return config_path


def _write_prepared_snapshot(snapshot_dir: Path, *, london_label: str, paris_label: str) -> None:
    snapshot_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "panel_id": "study2_british_within",
                "item_id": "study2_item_01",
                "answer_key": "london",
                "canonical_answer": london_label,
                "count": 80,
                "probability": 0.8,
            },
            {
                "panel_id": "study2_british_within",
                "item_id": "study2_item_01",
                "answer_key": "paris",
                "canonical_answer": paris_label,
                "count": 20,
                "probability": 0.2,
            },
        ]
    ).to_csv(snapshot_dir / "human_distributions.csv", index=False)
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
                "item_text_en": "Name a city",
                "item_text_zh": "city zh",
            }
        ]
    ).to_csv(snapshot_dir / "panel_items.csv", index=False)
    (snapshot_dir / "benchmark_manifest.json").write_text(
        json.dumps({"prepared_snapshot_id": snapshot_dir.name, "default_panel_id": "study2_british_within"}),
        encoding="utf-8",
    )


def _raw_row(
    *,
    prompt_language: str,
    sample_index: int,
    response_text: str,
    request_cache_key: str,
    error: str | None = None,
) -> dict[str, object]:
    return {
        "provider": "openai",
        "model": "fake",
        "panel_id": "study2_british_within",
        "item_id": "study2_item_01",
        "item_text_en": "Name a city",
        "item_text_zh": "city zh",
        "prompt_language": prompt_language,
        "answer_language": "English",
        "round_index": 1,
        "sample_index": sample_index,
        "temperature": 1.0,
        "max_output_tokens": 8,
        "seed": sample_index + 1,
        "request_cache_key": request_cache_key,
        "system_prompt": "system",
        "user_prompt": "user",
        "response_text": response_text,
        "finish_reason": "stop" if error is None else None,
        "request_id": request_cache_key,
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "total_tokens": 2,
        "latency_seconds": 0.1,
        "response_source": "provider_api" if error is None else "provider_error",
        "retry_count": 0,
        "attempt_count": 1,
        "cache_hit": False,
        "disk_cache_hit": False,
        "provider_cached_tokens": None,
        "error": error,
        "raw_payload": {},
        "generated_at_utc": "2026-03-24T00:00:00Z",
    }


def test_normalize_and_analyze_use_bound_snapshot_and_filter_incomplete_cells(tmp_path: Path, monkeypatch):
    prepared_root = tmp_path / "prepared"
    old_snapshot = prepared_root / "snapshot_old"
    new_snapshot = prepared_root / "snapshot_new"
    _write_prepared_snapshot(old_snapshot, london_label="old_london", paris_label="old_paris")
    _write_prepared_snapshot(new_snapshot, london_label="new_london", paris_label="new_paris")

    config_path = _write_config(tmp_path, round1_samples=2)

    run_dir = tmp_path / "runs" / "testrun"
    run_dir.mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"run_id": "testrun", "prepared_snapshot_id": "snapshot_old", "panel_id": "study2_british_within"}),
        encoding="utf-8",
    )
    raw_rows = [
        _raw_row(prompt_language="en", sample_index=0, response_text="London", request_cache_key="en-0"),
        _raw_row(prompt_language="en", sample_index=1, response_text="London", request_cache_key="en-1"),
        _raw_row(prompt_language="zh", sample_index=0, response_text="Paris", request_cache_key="zh-0"),
        _raw_row(prompt_language="zh", sample_index=1, response_text="", request_cache_key="zh-1", error="provider failed"),
    ]
    with (run_dir / "raw_generations.jsonl").open("w", encoding="utf-8") as handle:
        for row in raw_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    monkeypatch.setattr("coordbench.run_state.prepared_root", lambda: prepared_root)

    normalize_run(config_path, run_dir)
    analyze_run(config_path, run_dir)

    normalized = pd.read_csv(run_dir / "normalized_outputs.csv")
    assert set(normalized["canonical_answer"].dropna()) >= {"old_london", "old_paris"}
    assert "new_london" not in normalized["canonical_answer"].astype(str).tolist()

    cell_completeness = pd.read_csv(run_dir / "cell_completeness.csv")
    en_cell = cell_completeness[cell_completeness["prompt_language"] == "en"].iloc[0]
    zh_cell = cell_completeness[cell_completeness["prompt_language"] == "zh"].iloc[0]
    assert bool(en_cell["is_complete"]) is True
    assert bool(zh_cell["is_complete"]) is False

    metrics = pd.read_csv(run_dir / "item_metrics.csv")
    assert set(metrics["metric_family"]) == {"human_alignment"}
    assert metrics["prompt_language"].tolist() == ["en"]

    round2_candidates = pd.read_csv(run_dir / "round2_candidates.csv")
    assert round2_candidates.empty

    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["complete_cell_count"] == 1
    assert manifest["incomplete_cell_count"] == 1


def test_analyze_run_handles_empty_analyzable_data(tmp_path: Path, monkeypatch):
    prepared_root = tmp_path / "prepared"
    snapshot = prepared_root / "snapshot"
    _write_prepared_snapshot(snapshot, london_label="old_london", paris_label="old_paris")
    config_path = _write_config(tmp_path, round1_samples=2)

    run_dir = tmp_path / "runs" / "emptyrun"
    run_dir.mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"run_id": "emptyrun", "prepared_snapshot_id": "snapshot", "panel_id": "study2_british_within"}),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {
                "provider": "openai",
                "model": "fake",
                "panel_id": "study2_british_within",
                "item_id": "study2_item_01",
                "prompt_language": "en",
                "round_index": 1,
                "canonical_answer": "",
                "request_cache_key": "en-0",
                "error": "provider failed",
            }
        ]
    ).to_csv(run_dir / "normalized_outputs.csv", index=False)

    monkeypatch.setattr("coordbench.run_state.prepared_root", lambda: prepared_root)

    analyze_run(config_path, run_dir)

    metrics = pd.read_csv(run_dir / "item_metrics.csv")
    assert metrics.empty
    summary = json.loads((run_dir / "summary_metrics.json").read_text(encoding="utf-8"))
    assert summary == []
    round2_candidates = pd.read_csv(run_dir / "round2_candidates.csv")
    assert round2_candidates.empty
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert "analysis_warning" in manifest


def test_normalize_marks_service_errors_and_truncated_reasoning_invalid(tmp_path: Path, monkeypatch):
    prepared_root = tmp_path / "prepared"
    snapshot = prepared_root / "snapshot"
    _write_prepared_snapshot(snapshot, london_label="old_london", paris_label="old_paris")
    config_path = _write_config(tmp_path, round1_samples=2)

    run_dir = tmp_path / "runs" / "invalidrun"
    run_dir.mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"run_id": "invalidrun", "prepared_snapshot_id": "snapshot", "panel_id": "study2_british_within"}),
        encoding="utf-8",
    )
    raw_rows = [
        _raw_row(
            prompt_language="en",
            sample_index=0,
            response_text="Thinking Process:\n\n1. Analyze the request.",
            request_cache_key="en-0",
        ),
        _raw_row(
            prompt_language="en",
            sample_index=1,
            response_text="\u6a21\u578b\u300cQwen\u300d\u7684\u8bf7\u6c42\u8d1f\u8f7d\u8fc7\u9ad8\uff0c\u8bf7\u7a0d\u540e\u518d\u8bd5\u3002",
            request_cache_key="en-1",
        ),
        _raw_row(prompt_language="zh", sample_index=0, response_text="London", request_cache_key="zh-0"),
        _raw_row(prompt_language="zh", sample_index=1, response_text="London", request_cache_key="zh-1"),
    ]
    with (run_dir / "raw_generations.jsonl").open("w", encoding="utf-8") as handle:
        for row in raw_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    monkeypatch.setattr("coordbench.run_state.prepared_root", lambda: prepared_root)

    normalize_run(config_path, run_dir)
    normalized = pd.read_csv(run_dir / "normalized_outputs.csv")

    invalid_rows = normalized[normalized["prompt_language"] == "en"].reset_index(drop=True)
    assert invalid_rows["normalization_status"].tolist() == ["invalid", "invalid"]
    assert invalid_rows["canonical_answer"].fillna("").tolist() == ["", ""]

    valid_rows = normalized[normalized["prompt_language"] == "zh"].reset_index(drop=True)
    assert valid_rows["canonical_answer"].tolist() == ["old_london", "old_london"]


def test_round2_candidates_respect_configured_trigger(tmp_path: Path, monkeypatch):
    prepared_root = tmp_path / "prepared"
    snapshot = prepared_root / "snapshot"
    _write_prepared_snapshot(snapshot, london_label="old_london", paris_label="old_paris")
    monkeypatch.setattr("coordbench.run_state.prepared_root", lambda: prepared_root)

    raw_rows = [
        _raw_row(prompt_language="en", sample_index=0, response_text="Paris", request_cache_key="en-0"),
        _raw_row(prompt_language="en", sample_index=1, response_text="Paris", request_cache_key="en-1"),
        _raw_row(prompt_language="zh", sample_index=0, response_text="Paris", request_cache_key="zh-0"),
        _raw_row(prompt_language="zh", sample_index=1, response_text="Paris", request_cache_key="zh-1"),
    ]

    for trigger, should_select in [
        ("cross_lingual_top1_mismatch", False),
        ("human_top1_mismatch", True),
        ("either_top1_mismatch", True),
    ]:
        config_path = _write_config(tmp_path, round1_samples=2, round2_trigger=trigger)
        run_dir = tmp_path / "runs" / f"trigger-{trigger}"
        run_dir.mkdir(parents=True)
        (run_dir / "run_manifest.json").write_text(
            json.dumps({"run_id": run_dir.name, "prepared_snapshot_id": "snapshot", "panel_id": "study2_british_within"}),
            encoding="utf-8",
        )
        with (run_dir / "raw_generations.jsonl").open("w", encoding="utf-8") as handle:
            for row in raw_rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

        normalize_run(config_path, run_dir)
        analyze_run(config_path, run_dir)

        round2_candidates = pd.read_csv(run_dir / "round2_candidates.csv")
        if should_select:
            assert round2_candidates["item_id"].tolist() == ["study2_item_01"]
            assert round2_candidates["trigger"].tolist() == [trigger]
        else:
            assert round2_candidates.empty
