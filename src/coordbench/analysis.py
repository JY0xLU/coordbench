from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from coordbench.config import load_config
from coordbench.metrics import distribution_from_answers, focal_flip, jsd, spearman_frequency, top1_match, tvd
from coordbench.run_state import dedupe_request_records, prepared_snapshot_dir_for_run, resolve_run_dir
from coordbench.utils.files import read_json, write_json
from coordbench.utils.text import make_match_key

LOGGER = logging.getLogger(__name__)

ROUND2_TRIGGER_CROSS = "cross_lingual_top1_mismatch"
ROUND2_TRIGGER_HUMAN = "human_top1_mismatch"
ROUND2_TRIGGER_EITHER = "either_top1_mismatch"
VALID_ROUND2_TRIGGERS = {ROUND2_TRIGGER_CROSS, ROUND2_TRIGGER_HUMAN, ROUND2_TRIGGER_EITHER}

CELL_KEYS = ["provider", "model", "round_index", "panel_id", "item_id", "prompt_language"]
CELL_COMPLETENESS_COLUMNS = [
    *CELL_KEYS,
    "raw_record_count",
    "successful_samples",
    "expected_samples",
    "missing_samples",
    "completion_rate",
    "is_complete",
]
ITEM_METRIC_COLUMNS = [
    "metric_family",
    "provider",
    "model",
    "round_index",
    "panel_id",
    "item_id",
    "item_number",
    "human_top1_probability",
    "consensus_bucket",
    "prompt_language",
    "jsd",
    "tvd",
    "top1_match",
    "flip_rate",
    "spearman",
    "successful_samples",
    "expected_samples",
    "completion_rate",
    "en_successful_samples",
    "zh_successful_samples",
]
BOOTSTRAP_COLUMNS = [
    "scope",
    "metric_family",
    "provider",
    "model",
    "round_index",
    "panel_id",
    "item_id",
    "prompt_language",
    "metric",
    "ci_low",
    "ci_high",
]


def _empty_frame(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _item_distribution(frame: pd.DataFrame, answer_column: str) -> dict[str, float]:
    return distribution_from_answers(frame[answer_column].astype(str).tolist())


def _expected_samples(config, round_index: int) -> int:
    return config.sampling.round1_samples if int(round_index) == 1 else config.sampling.round2_samples


def _cell_completeness(normalized: pd.DataFrame, config, answer_column: str) -> pd.DataFrame:
    if normalized.empty:
        return _empty_frame(CELL_COMPLETENESS_COLUMNS)

    frame = normalized.copy()
    frame[answer_column] = frame[answer_column].fillna("").astype(str)
    grouped = (
        frame.groupby(CELL_KEYS, dropna=False)
        .agg(
            raw_record_count=(answer_column, "size"),
            successful_samples=(answer_column, lambda values: int((values != "").sum())),
        )
        .reset_index()
    )
    grouped["expected_samples"] = grouped["round_index"].astype(int).map(lambda idx: _expected_samples(config, idx))
    grouped["missing_samples"] = (grouped["expected_samples"] - grouped["successful_samples"]).clip(lower=0).astype(int)
    grouped["completion_rate"] = np.where(
        grouped["expected_samples"] > 0,
        grouped["successful_samples"] / grouped["expected_samples"],
        0.0,
    )
    grouped["is_complete"] = grouped["completion_rate"] >= config.analysis.min_cell_completion_rate
    return grouped[CELL_COMPLETENESS_COLUMNS].sort_values(CELL_KEYS).reset_index(drop=True)


def _cross_lingual_rows(
    normalized: pd.DataFrame,
    human_summary: pd.DataFrame,
    cell_completeness: pd.DataFrame,
    answer_column: str,
) -> list[dict[str, Any]]:
    if normalized.empty or cell_completeness.empty:
        return []

    rows: list[dict[str, Any]] = []
    consensus = human_summary.set_index(["panel_id", "item_id"])
    cell_lookup = cell_completeness.set_index(CELL_KEYS)
    grouped = normalized.groupby(["provider", "model", "round_index", "panel_id", "item_id"])
    for (provider, model, round_index, panel_id, item_id), group in grouped:
        en_key = (provider, model, round_index, panel_id, item_id, "en")
        zh_key = (provider, model, round_index, panel_id, item_id, "zh")
        if en_key not in cell_lookup.index or zh_key not in cell_lookup.index:
            continue
        en_stats = cell_lookup.loc[en_key]
        zh_stats = cell_lookup.loc[zh_key]
        if not bool(en_stats["is_complete"]) or not bool(zh_stats["is_complete"]):
            continue

        lang_groups = {language: subset for language, subset in group.groupby("prompt_language")}
        if "en" not in lang_groups or "zh" not in lang_groups:
            continue
        en_dist = _item_distribution(lang_groups["en"], answer_column)
        zh_dist = _item_distribution(lang_groups["zh"], answer_column)
        stats = consensus.loc[(panel_id, item_id)]
        rows.append(
            {
                "metric_family": "cross_lingual",
                "provider": provider,
                "model": model,
                "round_index": round_index,
                "panel_id": panel_id,
                "item_id": item_id,
                "item_number": int(stats["item_number"]),
                "human_top1_probability": float(stats["human_top1_probability"]),
                "consensus_bucket": stats["consensus_bucket"],
                "prompt_language": "en_vs_zh",
                "jsd": jsd(en_dist, zh_dist),
                "tvd": tvd(en_dist, zh_dist),
                "top1_match": top1_match(en_dist, zh_dist),
                "flip_rate": focal_flip(en_dist, zh_dist),
                "spearman": spearman_frequency(en_dist, zh_dist),
                "successful_samples": int(min(en_stats["successful_samples"], zh_stats["successful_samples"])),
                "expected_samples": int(en_stats["expected_samples"]),
                "completion_rate": float(min(en_stats["completion_rate"], zh_stats["completion_rate"])),
                "en_successful_samples": int(en_stats["successful_samples"]),
                "zh_successful_samples": int(zh_stats["successful_samples"]),
            }
        )
    return rows


def _human_alignment_rows(
    normalized: pd.DataFrame,
    human: pd.DataFrame,
    human_summary: pd.DataFrame,
    cell_completeness: pd.DataFrame,
    answer_column: str,
) -> list[dict[str, Any]]:
    if normalized.empty or cell_completeness.empty:
        return []

    rows: list[dict[str, Any]] = []
    consensus = human_summary.set_index(["panel_id", "item_id"])
    cell_lookup = cell_completeness.set_index(CELL_KEYS)
    human_dists = {
        (panel_id, item_id): {
            row.canonical_answer: row.probability
            for row in group.itertuples()
        }
        for (panel_id, item_id), group in human.groupby(["panel_id", "item_id"])
    }
    grouped = normalized.groupby(["provider", "model", "round_index", "panel_id", "item_id", "prompt_language"])
    for (provider, model, round_index, panel_id, item_id, prompt_language), group in grouped:
        cell_key = (provider, model, round_index, panel_id, item_id, prompt_language)
        if cell_key not in cell_lookup.index:
            continue
        cell_stats = cell_lookup.loc[cell_key]
        if not bool(cell_stats["is_complete"]):
            continue
        llm_dist = _item_distribution(group, answer_column)
        human_dist = human_dists[(panel_id, item_id)]
        stats = consensus.loc[(panel_id, item_id)]
        rows.append(
            {
                "metric_family": "human_alignment",
                "provider": provider,
                "model": model,
                "round_index": round_index,
                "panel_id": panel_id,
                "item_id": item_id,
                "item_number": int(stats["item_number"]),
                "human_top1_probability": float(stats["human_top1_probability"]),
                "consensus_bucket": stats["consensus_bucket"],
                "prompt_language": prompt_language,
                "jsd": jsd(llm_dist, human_dist),
                "tvd": tvd(llm_dist, human_dist),
                "top1_match": top1_match(llm_dist, human_dist),
                "flip_rate": None,
                "spearman": spearman_frequency(llm_dist, human_dist),
                "successful_samples": int(cell_stats["successful_samples"]),
                "expected_samples": int(cell_stats["expected_samples"]),
                "completion_rate": float(cell_stats["completion_rate"]),
                "en_successful_samples": None,
                "zh_successful_samples": None,
            }
        )
    return rows


def _bootstrap_mean(values: np.ndarray, resamples: int, seed: int = 20260324) -> tuple[float, float]:
    if values.size == 0:
        return (0.0, 0.0)
    rng = np.random.default_rng(seed)
    samples = []
    for _ in range(resamples):
        draw = rng.choice(values, size=len(values), replace=True)
        samples.append(float(np.mean(draw)))
    return (float(np.quantile(samples, 0.025)), float(np.quantile(samples, 0.975)))


def _item_level_bootstrap(
    cross_lingual_normalized: pd.DataFrame,
    human_alignment_normalized: pd.DataFrame,
    human: pd.DataFrame,
    resamples: int,
) -> list[dict[str, Any]]:
    if cross_lingual_normalized.empty and human_alignment_normalized.empty:
        return []

    rows: list[dict[str, Any]] = []
    rng = np.random.default_rng(20260324)
    human_dists = {
        (panel_id, item_id): {
            row.canonical_answer: row.probability
            for row in group.itertuples()
        }
        for (panel_id, item_id), group in human.groupby(["panel_id", "item_id"])
    }

    cross_grouped = cross_lingual_normalized.groupby(["provider", "model", "round_index", "panel_id", "item_id"])
    for (provider, model, round_index, panel_id, item_id), group in cross_grouped:
        lang_groups = {language: subset for language, subset in group.groupby("prompt_language")}
        if "en" not in lang_groups or "zh" not in lang_groups:
            continue
        en_answers = lang_groups["en"]["coord_answer"].astype(str).to_numpy()
        zh_answers = lang_groups["zh"]["coord_answer"].astype(str).to_numpy()
        if len(en_answers) == 0 or len(zh_answers) == 0:
            continue
        jsd_values = []
        tvd_values = []
        spearman_values = []
        for _ in range(resamples):
            en_draw = rng.choice(en_answers, size=len(en_answers), replace=True)
            zh_draw = rng.choice(zh_answers, size=len(zh_answers), replace=True)
            en_dist = distribution_from_answers(en_draw)
            zh_dist = distribution_from_answers(zh_draw)
            jsd_values.append(jsd(en_dist, zh_dist))
            tvd_values.append(tvd(en_dist, zh_dist))
            sp = spearman_frequency(en_dist, zh_dist)
            if sp is not None:
                spearman_values.append(sp)
        for metric_name, metric_values in [("jsd", jsd_values), ("tvd", tvd_values), ("spearman", spearman_values)]:
            if not metric_values:
                continue
            rows.append(
                {
                    "scope": "item",
                    "metric_family": "cross_lingual",
                    "provider": provider,
                    "model": model,
                    "round_index": round_index,
                    "panel_id": panel_id,
                    "item_id": item_id,
                    "prompt_language": "en_vs_zh",
                    "metric": metric_name,
                    "ci_low": float(np.quantile(metric_values, 0.025)),
                    "ci_high": float(np.quantile(metric_values, 0.975)),
                }
            )

    human_grouped = human_alignment_normalized.groupby(
        ["provider", "model", "round_index", "panel_id", "item_id", "prompt_language"]
    )
    for (provider, model, round_index, panel_id, item_id, prompt_language), subset in human_grouped:
        if (panel_id, item_id) not in human_dists:
            continue
        llm_answers = subset["canonical_answer"].astype(str).to_numpy()
        if len(llm_answers) == 0:
            continue
        human_dist = human_dists[(panel_id, item_id)]
        jsd_values = []
        tvd_values = []
        spearman_values = []
        for _ in range(resamples):
            llm_draw = rng.choice(llm_answers, size=len(llm_answers), replace=True)
            llm_dist = distribution_from_answers(llm_draw)
            jsd_values.append(jsd(llm_dist, human_dist))
            tvd_values.append(tvd(llm_dist, human_dist))
            sp = spearman_frequency(llm_dist, human_dist)
            if sp is not None:
                spearman_values.append(sp)
        for metric_name, metric_values in [("jsd", jsd_values), ("tvd", tvd_values), ("spearman", spearman_values)]:
            if not metric_values:
                continue
            rows.append(
                {
                    "scope": "item",
                    "metric_family": "human_alignment",
                    "provider": provider,
                    "model": model,
                    "round_index": round_index,
                    "panel_id": panel_id,
                    "item_id": item_id,
                    "prompt_language": prompt_language,
                    "metric": metric_name,
                    "ci_low": float(np.quantile(metric_values, 0.025)),
                    "ci_high": float(np.quantile(metric_values, 0.975)),
                }
            )
    return rows


def _ensure_coord_answer(frame: pd.DataFrame) -> pd.DataFrame:
    if "coord_answer" in frame.columns:
        frame["coord_answer"] = frame["coord_answer"].fillna("").astype(str)
        return frame

    if "response_clean" in frame.columns:
        frame["coord_answer"] = frame["response_clean"].fillna("").astype(str)
    else:
        frame["coord_answer"] = ""
    if "response_validation_error" in frame.columns:
        validation_error = frame["response_validation_error"].fillna("").astype(str).str.strip().str.lower()
        valid_mask = validation_error.isin({"", "nan", "none"})
        frame.loc[~valid_mask, "coord_answer"] = ""
    return frame


def _ensure_coord_answer_key(frame: pd.DataFrame) -> pd.DataFrame:
    if "coord_answer_key" in frame.columns:
        frame["coord_answer_key"] = frame["coord_answer_key"].fillna("").astype(str)
        return frame
    frame["coord_answer_key"] = frame["coord_answer"].fillna("").astype(str).map(make_match_key)
    return frame


def _round2_candidates(item_metrics: pd.DataFrame, round2_trigger: str) -> pd.DataFrame:
    if item_metrics.empty:
        return pd.DataFrame(columns=["item_id", "trigger"])

    selected_trigger = round2_trigger
    if selected_trigger not in VALID_ROUND2_TRIGGERS:
        LOGGER.warning("Unknown round2_trigger=%s; fallback to %s", selected_trigger, ROUND2_TRIGGER_CROSS)
        selected_trigger = ROUND2_TRIGGER_CROSS

    round1 = item_metrics[item_metrics["round_index"] == 1]
    cross_ids = set(
        round1[
            (round1["metric_family"] == "cross_lingual")
            & (round1["top1_match"] == 0)
        ]["item_id"].astype(str)
    )
    human_ids = set(
        round1[
            (round1["metric_family"] == "human_alignment")
            & (round1["top1_match"] == 0)
        ]["item_id"].astype(str)
    )

    if selected_trigger == ROUND2_TRIGGER_CROSS:
        item_ids = cross_ids
    elif selected_trigger == ROUND2_TRIGGER_HUMAN:
        item_ids = human_ids
    else:
        item_ids = cross_ids | human_ids

    if not item_ids:
        return pd.DataFrame(columns=["item_id", "trigger"])

    round2_candidates = pd.DataFrame({"item_id": sorted(item_ids)})
    round2_candidates["trigger"] = selected_trigger
    return round2_candidates


def analyze_run(config_path: str | Path, run_id: str | Path) -> Path:
    config = load_config(config_path)
    run_dir = resolve_run_dir(config.outputs.run_root, run_id)
    prepared_dir = prepared_snapshot_dir_for_run(run_dir)

    normalized_all = pd.read_csv(run_dir / "normalized_outputs.csv")
    normalized_all = normalized_all[normalized_all["panel_id"] == config.sampling.panel_id].copy()
    if not normalized_all.empty:
        deduped_rows = dedupe_request_records(normalized_all.to_dict(orient="records"))
        if len(deduped_rows) != len(normalized_all):
            LOGGER.info(
                "Deduped normalized outputs for %s from %s rows to %s rows",
                run_dir,
                len(normalized_all),
                len(deduped_rows),
            )
        normalized_all = pd.DataFrame(deduped_rows)
    normalized_all = _ensure_coord_answer(normalized_all)
    normalized_all = _ensure_coord_answer_key(normalized_all)
    normalized_all["canonical_answer"] = normalized_all["canonical_answer"].fillna("").astype(str)

    human = pd.read_csv(prepared_dir / "human_distributions.csv")
    human = human[human["panel_id"] == config.sampling.panel_id].copy()
    panel_items = pd.read_csv(prepared_dir / "panel_items.csv")
    panel_items = panel_items[panel_items["panel_id"] == config.sampling.panel_id].copy()
    human_summary = (
        human.groupby(["panel_id", "item_id"])
        .agg(human_top1_probability=("probability", "max"))
        .reset_index()
        .merge(panel_items[["panel_id", "item_id", "item_number"]].drop_duplicates(), on=["panel_id", "item_id"])
    )
    top1_values = human_summary["human_top1_probability"]
    quantiles = top1_values.quantile([1 / 3, 2 / 3]).tolist()

    def bucketize(value: float) -> str:
        if value <= quantiles[0]:
            return "low"
        if value <= quantiles[1]:
            return "medium"
        return "high"

    human_summary["consensus_bucket"] = human_summary["human_top1_probability"].map(bucketize)

    cell_completeness = _cell_completeness(normalized_all, config, "canonical_answer")
    cell_completeness.to_csv(run_dir / "cell_completeness.csv", index=False)
    coord_cell_completeness = _cell_completeness(normalized_all, config, "coord_answer_key")
    coord_cell_completeness.to_csv(run_dir / "coord_cell_completeness.csv", index=False)

    cross_lingual_normalized = normalized_all[normalized_all["coord_answer_key"] != ""].copy()
    if not cross_lingual_normalized.empty and not coord_cell_completeness.empty:
        cross_lingual_normalized = cross_lingual_normalized.merge(coord_cell_completeness, on=CELL_KEYS, how="left")
        cross_lingual_normalized = cross_lingual_normalized[cross_lingual_normalized["is_complete"].fillna(False)].copy()

    human_alignment_normalized = normalized_all[normalized_all["canonical_answer"] != ""].copy()
    if not human_alignment_normalized.empty and not cell_completeness.empty:
        human_alignment_normalized = human_alignment_normalized.merge(cell_completeness, on=CELL_KEYS, how="left")
        human_alignment_normalized = human_alignment_normalized[
            human_alignment_normalized["is_complete"].fillna(False)
        ].copy()

    rows = _cross_lingual_rows(
        cross_lingual_normalized,
        human_summary,
        coord_cell_completeness,
        answer_column="coord_answer_key",
    ) + _human_alignment_rows(
        human_alignment_normalized,
        human,
        human_summary,
        cell_completeness,
        answer_column="canonical_answer",
    )
    item_metrics = pd.DataFrame(rows, columns=ITEM_METRIC_COLUMNS)
    if not item_metrics.empty:
        item_metrics = item_metrics.sort_values(
            ["metric_family", "provider", "model", "round_index", "item_number", "prompt_language"]
        )
    item_metrics.to_csv(run_dir / "item_metrics.csv", index=False)

    summary_rows: list[dict[str, Any]] = []
    if not item_metrics.empty:
        for keys, group in item_metrics.groupby(["metric_family", "provider", "model", "round_index", "prompt_language"]):
            metric_family, provider, model, round_index, prompt_language = keys
            summary_rows.append(
                {
                    "metric_family": metric_family,
                    "provider": provider,
                    "model": model,
                    "round_index": int(round_index),
                    "prompt_language": prompt_language,
                    "mean_jsd": float(group["jsd"].mean()),
                    "mean_tvd": float(group["tvd"].mean()),
                    "mean_top1_match": float(group["top1_match"].mean()),
                    "mean_flip_rate": float(group["flip_rate"].mean()),
                    "mean_spearman": float(group["spearman"].dropna().mean()) if group["spearman"].notna().any() else None,
                    "item_count": int(group.shape[0]),
                }
            )
    write_json(run_dir / "summary_metrics.json", summary_rows)

    bootstrap_rows: list[dict[str, Any]] = []
    for summary in summary_rows:
        subset = item_metrics[
            (item_metrics["metric_family"] == summary["metric_family"])
            & (item_metrics["provider"] == summary["provider"])
            & (item_metrics["model"] == summary["model"])
            & (item_metrics["round_index"] == summary["round_index"])
            & (item_metrics["prompt_language"] == summary["prompt_language"])
        ]
        metrics = ["jsd", "tvd", "top1_match", "flip_rate"]
        if summary["metric_family"] != "cross_lingual":
            metrics = ["jsd", "tvd", "top1_match"]
        for metric in metrics:
            ci_low, ci_high = _bootstrap_mean(
                subset[metric].to_numpy(dtype=float),
                config.analysis.bootstrap_resamples,
            )
            bootstrap_rows.append(
                {
                    "scope": "aggregate",
                    "metric_family": summary["metric_family"],
                    "provider": summary["provider"],
                    "model": summary["model"],
                    "round_index": summary["round_index"],
                    "panel_id": config.sampling.panel_id,
                    "item_id": None,
                    "prompt_language": summary["prompt_language"],
                    "metric": metric,
                    "ci_low": ci_low,
                    "ci_high": ci_high,
                }
            )
    bootstrap_rows.extend(
        _item_level_bootstrap(
            cross_lingual_normalized,
            human_alignment_normalized,
            human,
            config.analysis.item_bootstrap_resamples,
        )
    )
    pd.DataFrame(bootstrap_rows, columns=BOOTSTRAP_COLUMNS).to_csv(run_dir / "bootstrap_intervals.csv", index=False)

    round2_candidates = _round2_candidates(item_metrics, config.sampling.round2_trigger)
    round2_candidates.to_csv(run_dir / "round2_candidates.csv", index=False)

    manifest = read_json(run_dir / "run_manifest.json")
    manifest["analysis_completed"] = True
    manifest["cell_completion_threshold"] = config.analysis.min_cell_completion_rate
    manifest["complete_cell_count"] = int(cell_completeness["is_complete"].sum()) if not cell_completeness.empty else 0
    manifest["incomplete_cell_count"] = int((~cell_completeness["is_complete"]).sum()) if not cell_completeness.empty else 0
    manifest["complete_cell_count_human_alignment"] = (
        int(cell_completeness["is_complete"].sum()) if not cell_completeness.empty else 0
    )
    manifest["incomplete_cell_count_human_alignment"] = (
        int((~cell_completeness["is_complete"]).sum()) if not cell_completeness.empty else 0
    )
    manifest["complete_cell_count_cross_lingual"] = (
        int(coord_cell_completeness["is_complete"].sum()) if not coord_cell_completeness.empty else 0
    )
    manifest["incomplete_cell_count_cross_lingual"] = (
        int((~coord_cell_completeness["is_complete"]).sum()) if not coord_cell_completeness.empty else 0
    )
    manifest["item_metric_count"] = int(item_metrics.shape[0])
    manifest["round2_candidate_count"] = int(round2_candidates.shape[0])
    if item_metrics.empty:
        manifest["analysis_warning"] = "No analyzable item metrics were produced after completeness filtering."
    else:
        manifest.pop("analysis_warning", None)
    write_json(run_dir / "run_manifest.json", manifest)
    LOGGER.info("Analyzed run into %s", run_dir)
    return run_dir
