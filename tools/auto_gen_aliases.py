from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate alias seed rows from one run's normalized outputs.")
    parser.add_argument("--run-id", required=True, help="Run id under artifacts/runs/<run_id>.")
    parser.add_argument(
        "--run-root",
        default="artifacts/runs",
        help="Run root directory where run-id subfolders are stored.",
    )
    parser.add_argument(
        "--alias-file",
        default="data/aliases/default_aliases.csv",
        help="Alias output csv path.",
    )
    args = parser.parse_args()

    run_root = Path(args.run_root).resolve()
    norm_file = run_root / args.run_id / "normalized_outputs.csv"
    alias_file = Path(args.alias_file).resolve()

    if not norm_file.exists():
        raise SystemExit(f"normalized_outputs.csv not found: {norm_file}")

    df = pd.read_csv(norm_file)
    if "parsed_answer" not in df.columns:
        raise SystemExit("parsed_answer column missing in normalized_outputs.csv")

    subset = df[df["parsed_answer"].notna()][["panel_id", "item_id", "parsed_answer"]].copy()
    subset.columns = ["panel_id", "item_id", "surface_form"]
    subset["canonical_answer"] = subset["surface_form"]
    subset["notes"] = f"auto-generated from run {args.run_id}"

    alias_file.parent.mkdir(parents=True, exist_ok=True)
    subset.to_csv(alias_file, index=False)
    print(f"Generated {len(subset)} alias entries into {alias_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
