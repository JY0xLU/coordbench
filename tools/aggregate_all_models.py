from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any] | list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_first_model(path: Path) -> str:
    if not path.exists():
        return "unknown"
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            return str(payload.get("model", "unknown"))
    return "unknown"


def _summary_metrics(path: Path) -> tuple[str, str, str, str]:
    if not path.exists():
        return ("N/A", "N/A", "N/A", "N/A")
    payload = _read_json(path)
    if not isinstance(payload, list):
        return ("N/A", "N/A", "N/A", "N/A")

    cross_jsd = "N/A"
    cross_top1 = "N/A"
    human_en_jsd = "N/A"
    human_zh_jsd = "N/A"
    for row in payload:
        if not isinstance(row, dict):
            continue
        if row.get("metric_family") == "cross_lingual" and int(row.get("round_index", 0)) == 1:
            jsd = row.get("mean_jsd")
            top1 = row.get("mean_top1_match")
            cross_jsd = f"{jsd:.4f}" if isinstance(jsd, (float, int)) else str(jsd)
            cross_top1 = f"{top1:.4f}" if isinstance(top1, (float, int)) else str(top1)
        if row.get("metric_family") == "human_alignment" and int(row.get("round_index", 0)) == 1:
            lang = str(row.get("prompt_language", ""))
            jsd = row.get("mean_jsd")
            jsd_text = f"{jsd:.4f}" if isinstance(jsd, (float, int)) else str(jsd)
            if lang in {"en", "English"}:
                human_en_jsd = jsd_text
            elif lang == "zh":
                human_zh_jsd = jsd_text
    return (cross_jsd, cross_top1, human_en_jsd, human_zh_jsd)


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate all model runs under artifacts/full_experiments.")
    parser.add_argument(
        "--artifacts-root",
        default="artifacts/full_experiments",
        help="Root folder containing full experiment run trees.",
    )
    args = parser.parse_args()

    base_dir = Path(args.artifacts_root).resolve()
    if not base_dir.exists():
        raise SystemExit(f"Directory not found: {base_dir}")

    results: list[tuple[str, int, int, str, str, str, str]] = []
    for run_manifest in sorted(base_dir.rglob("run_manifest.json")):
        run_dir = run_manifest.parent
        manifest = _read_json(run_manifest)
        if not isinstance(manifest, dict):
            continue
        model = _read_first_model(run_dir / "raw_generations.jsonl")
        raw_count = int(manifest.get("raw_record_count", 0) or 0)
        unresolved = int(manifest.get("unresolved_count", 0) or 0)
        cross_jsd, cross_top1, human_en, human_zh = _summary_metrics(run_dir / "summary_metrics.json")
        results.append((model, raw_count, unresolved, cross_jsd, cross_top1, human_en, human_zh))

    def sort_key(row: tuple[str, int, int, str, str, str, str]) -> float:
        try:
            return float(row[3])
        except ValueError:
            return 999.0

    results.sort(key=sort_key)

    print("| Model | Samples | Unresolved | R1 Cross JSD | R1 Cross Top1 | R1 Human EN JSD | R1 Human ZH JSD |")
    print("|---|---:|---:|---:|---:|---:|---:|")
    for row in results:
        print(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} | {row[5]} | {row[6]} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
