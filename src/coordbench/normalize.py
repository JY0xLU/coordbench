from __future__ import annotations

import logging
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
from rapidfuzz import fuzz, process

from coordbench.config import load_config
from coordbench.response_validation import response_validation_error
from coordbench.run_state import dedupe_request_records, prepared_snapshot_dir_for_run, resolve_run_dir
from coordbench.utils.files import read_json, read_jsonl, write_json
from coordbench.utils.text import clean_surface, extract_first_answer_line, make_match_key

LOGGER = logging.getLogger(__name__)
MOUNT_PREFIXES = {"mount", "mt", "mountain"}
PERSON_OVERLAP_ITEM_IDS = {
    "study2_item_02",
    "study2_item_03",
    "study2_item_08",
    "study2_item_12",
}


def _load_aliases(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["panel_id", "item_id", "surface_form", "canonical_answer", "notes"])
    aliases = pd.read_csv(path)
    for column in ["panel_id", "item_id", "surface_form", "canonical_answer", "notes"]:
        if column not in aliases.columns:
            aliases[column] = ""
    aliases["surface_key"] = aliases["surface_form"].astype(str).map(make_match_key)
    return aliases


def _auto_aliases_from_participant_data(
    prepared_dir: Path,
    human_lookup: dict[tuple[str, str, str], str],
) -> pd.DataFrame:
    participant_path = prepared_dir / "participant_responses.csv"
    if not participant_path.exists():
        return pd.DataFrame(columns=["panel_id", "item_id", "surface_form", "canonical_answer", "notes", "surface_key"])
    participant = pd.read_csv(participant_path)
    required = {"panel_id", "item_id", "answer_key", "response_original", "response_clean"}
    if not required.issubset(participant.columns):
        return pd.DataFrame(columns=["panel_id", "item_id", "surface_form", "canonical_answer", "notes", "surface_key"])

    rows: list[dict[str, str]] = []
    for row in participant.itertuples():
        key = (str(row.panel_id), str(row.item_id), str(row.answer_key))
        canonical = human_lookup.get(key)
        if not canonical:
            continue
        for surface in [str(row.response_original or "").strip(), str(row.response_clean or "").strip(), canonical]:
            surface = surface.strip()
            if not surface:
                continue
            rows.append(
                {
                    "panel_id": str(row.panel_id),
                    "item_id": str(row.item_id),
                    "surface_form": surface,
                    "canonical_answer": canonical,
                    "notes": "auto_synced_from_participant_responses",
                }
            )
    if not rows:
        return pd.DataFrame(columns=["panel_id", "item_id", "surface_form", "canonical_answer", "notes", "surface_key"])
    frame = pd.DataFrame(rows).drop_duplicates(subset=["panel_id", "item_id", "surface_form", "canonical_answer"])
    frame["surface_key"] = frame["surface_form"].astype(str).map(make_match_key)
    return frame


def _alias_coverage_report(
    aliases: pd.DataFrame,
    human: pd.DataFrame,
) -> pd.DataFrame:
    if human.empty:
        return pd.DataFrame(
            columns=[
                "panel_id",
                "item_id",
                "human_answer_key_count",
                "alias_surface_key_count",
                "covered_human_answer_key_count",
                "coverage_rate",
            ]
        )
    alias_keys = (
        aliases.groupby(["panel_id", "item_id"], dropna=False)["surface_key"]
        .apply(lambda values: {str(v) for v in values if str(v)})
        .to_dict()
    )
    rows: list[dict[str, Any]] = []
    for (panel_id, item_id), group in human.groupby(["panel_id", "item_id"]):
        human_keys = {str(row.answer_key) for row in group.itertuples() if str(row.answer_key)}
        global_alias = alias_keys.get(("", ""), set())
        panel_global_alias = alias_keys.get((panel_id, ""), set())
        item_global_alias = alias_keys.get(("", item_id), set())
        scoped_alias = alias_keys.get((panel_id, item_id), set())
        all_alias = global_alias | panel_global_alias | item_global_alias | scoped_alias
        covered = human_keys & all_alias
        rows.append(
            {
                "panel_id": panel_id,
                "item_id": item_id,
                "human_answer_key_count": len(human_keys),
                "alias_surface_key_count": len(all_alias),
                "covered_human_answer_key_count": len(covered),
                "coverage_rate": (len(covered) / len(human_keys)) if human_keys else 1.0,
            }
        )
    return pd.DataFrame(rows).sort_values(["panel_id", "item_id"]).reset_index(drop=True)


def _coord_key(response_clean: str, item_id: str) -> str:
    text = clean_surface(str(response_clean or ""))
    if not text:
        return ""

    tokens = re.findall(r"[A-Za-z0-9]+", text)
    if not tokens:
        return make_match_key(text)

    lowered = [token.lower() for token in tokens]
    if lowered and lowered[0] in MOUNT_PREFIXES and len(tokens) > 1:
        tokens = tokens[1:]
        lowered = lowered[1:]

    if str(item_id) in PERSON_OVERLAP_ITEM_IDS:
        alpha_tokens = [token for token in tokens if token.isalpha()]
        if len(alpha_tokens) >= 2:
            # Treat full-name/last-name variants as the same coordination focal point.
            return make_match_key(alpha_tokens[-1])

    return make_match_key(" ".join(tokens))


def normalize_run(
    config_path: str | Path,
    run_id: str | Path,
    *,
    allow_unmapped_override: bool | None = None,
) -> Path:
    config = load_config(config_path)
    if allow_unmapped_override is not None:
        config = replace(
            config,
            normalization=replace(config.normalization, allow_unmapped=allow_unmapped_override),
        )
    run_dir = resolve_run_dir(config.outputs.run_root, run_id)
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")
    prepared_dir = prepared_snapshot_dir_for_run(run_dir)

    raw_rows = read_jsonl(run_dir / "raw_generations.jsonl")
    if not raw_rows:
        raise RuntimeError("No raw generations found for normalization.")
    deduped_rows = dedupe_request_records(raw_rows)
    if len(deduped_rows) != len(raw_rows):
        LOGGER.info("Deduped raw generations for %s from %s rows to %s rows", run_dir, len(raw_rows), len(deduped_rows))

    frame = pd.DataFrame(deduped_rows)
    frame["response_validation_error"] = frame.apply(
        lambda row: response_validation_error(
            text=str(row.get("response_text") or ""),
            finish_reason=row.get("finish_reason"),
            error=row.get("error"),
        ),
        axis=1,
    )
    frame["parsed_answer"] = frame["response_text"].astype(str).map(extract_first_answer_line)
    frame["response_clean"] = frame["parsed_answer"].map(clean_surface)
    frame["answer_key"] = frame["response_clean"].map(make_match_key)

    human = pd.read_csv(prepared_dir / "human_distributions.csv")
    human_lookup: dict[tuple[str, str, str], str] = {
        (row.panel_id, row.item_id, row.answer_key): row.canonical_answer for row in human.itertuples()
    }
    aliases = _load_aliases(config.normalization.alias_path)
    auto_aliases = _auto_aliases_from_participant_data(prepared_dir, human_lookup)
    if not auto_aliases.empty:
        aliases = pd.concat([aliases, auto_aliases], ignore_index=True)
        aliases = aliases.drop_duplicates(subset=["panel_id", "item_id", "surface_key", "canonical_answer"])

    coverage_report = _alias_coverage_report(aliases, human)
    coverage_report.to_csv(run_dir / "alias_coverage_report.csv", index=False)

    human_candidates: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for (panel_id, item_id), group in human.groupby(["panel_id", "item_id"]):
        human_candidates[(panel_id, item_id)] = [
            (row.answer_key, row.canonical_answer) for row in group.itertuples()
        ]

    normalized_rows: list[dict[str, Any]] = []
    unresolved_rows: list[dict[str, Any]] = []
    for row in frame.to_dict(orient="records"):
        panel_id = row["panel_id"]
        item_id = row["item_id"]
        answer_key = row["answer_key"]
        coord_answer = ""
        coord_answer_key = ""
        canonical_answer = ""
        status = "invalid"
        validation_error_raw = row.get("response_validation_error")
        validation_error_text = str(validation_error_raw).strip()
        if pd.isna(validation_error_raw) or validation_error_text.lower() in {"", "nan", "none"}:
            validation_error = None
        else:
            validation_error = validation_error_text

        if not validation_error and answer_key:
            coord_answer = row["response_clean"]
            coord_answer_key = _coord_key(coord_answer, item_id)
            alias_matches = aliases[
                ((aliases["panel_id"].fillna("") == panel_id) | (aliases["panel_id"].fillna("") == ""))
                & ((aliases["item_id"].fillna("") == item_id) | (aliases["item_id"].fillna("") == ""))
                & (aliases["surface_key"] == answer_key)
            ]
            if not alias_matches.empty:
                canonical_answer = str(alias_matches.iloc[0]["canonical_answer"])
                coord_answer_key = make_match_key(canonical_answer)
                status = "alias"
            elif (panel_id, item_id, answer_key) in human_lookup:
                canonical_answer = human_lookup[(panel_id, item_id, answer_key)]
                status = "human_key"
            else:
                candidates = human_candidates.get((panel_id, item_id), [])
                candidate_keys = [candidate_key for candidate_key, _ in candidates if candidate_key]
                best = process.extractOne(answer_key, candidate_keys, scorer=fuzz.ratio) if candidate_keys else None
                if best and best[1] >= config.normalization.fuzzy_match_threshold:
                    matched_key = best[0]
                    for candidate_key, candidate_answer in candidates:
                        if candidate_key == matched_key:
                            canonical_answer = candidate_answer
                            status = "fuzzy"
                            break
                elif config.normalization.allow_unmapped:
                    canonical_answer = row["response_clean"]
                    status = "unmapped"
                else:
                    status = "unmapped"

        closest_human_key = ""
        closest_human_canonical = ""
        closest_human_score = None
        if answer_key:
            candidates = human_candidates.get((panel_id, item_id), [])
            candidate_keys = [candidate_key for candidate_key, _ in candidates if candidate_key]
            nearest = process.extractOne(answer_key, candidate_keys, scorer=fuzz.ratio) if candidate_keys else None
            if nearest:
                closest_human_key = str(nearest[0])
                closest_human_score = float(nearest[1])
                for candidate_key, candidate_answer in candidates:
                    if candidate_key == closest_human_key:
                        closest_human_canonical = str(candidate_answer)
                        break

        normalized = {
            **row,
            "coord_answer": coord_answer,
            "coord_answer_key": coord_answer_key,
            "canonical_answer": canonical_answer,
            "normalization_status": status,
            "closest_human_answer_key": closest_human_key,
            "closest_human_canonical": closest_human_canonical,
            "closest_human_score": closest_human_score,
        }
        normalized_rows.append(normalized)
        if status in {"invalid", "unmapped"}:
            unresolved_rows.append(normalized)

    normalized_frame = pd.DataFrame(normalized_rows)
    normalized_frame.to_csv(run_dir / "normalized_outputs.csv", index=False)
    pd.DataFrame(unresolved_rows).to_csv(run_dir / "unresolved_queue.csv", index=False)

    manifest = read_json(run_dir / "run_manifest.json")
    manifest["normalization_completed"] = True
    manifest["unresolved_count"] = len(unresolved_rows)
    manifest["raw_record_count"] = len(raw_rows)
    manifest["deduped_raw_record_count"] = len(deduped_rows)
    write_json(run_dir / "run_manifest.json", manifest)

    if unresolved_rows and not config.normalization.allow_unmapped:
        raise RuntimeError(
            "Normalization produced unresolved outputs. Review unresolved_queue.csv or set allow_unmapped=true."
        )
    LOGGER.info("Normalized outputs into %s", run_dir)
    return run_dir
