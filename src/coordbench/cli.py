from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from coordbench.analysis import analyze_run
from coordbench.config import load_config
from coordbench.dataset.osf import fetch_source_data, latest_source_snapshot
from coordbench.dataset.prepare import prepare_human_panels
from coordbench.dataset.profile import latest_prepared_snapshot, profile_dataset
from coordbench.logging_utils import configure_logging
from coordbench.normalize import normalize_run
from coordbench.plots import plot_run
from coordbench.runner import run_sampling
try:
    from track_b_agent.integrated.pipeline import run_track_b as run_track_b_agent
except Exception:  # noqa: BLE001
    run_track_b_agent = None


def _resolve_run_dir(config_path: str | Path, run_id: str) -> Path:
    config = load_config(config_path)
    path = Path(run_id)
    return path if path.is_absolute() else config.outputs.run_root / run_id


def _run_all(config_path: str | Path) -> Path:
    source_dir = latest_source_snapshot()
    if source_dir is None:
        source_dir = fetch_source_data()

    prepared_dir = latest_prepared_snapshot()
    if prepared_dir is None or prepared_dir.name != source_dir.name:
        prepared_dir = prepare_human_panels(source_dir)
    profile_dataset(prepared_dir)

    run_dir = run_sampling(config_path, round_index=1)
    normalize_run(config_path, run_dir)
    analyze_run(config_path, run_dir)

    config = load_config(config_path)
    if config.sampling.enable_round2:
        candidates_path = run_dir / "round2_candidates.csv"
        if candidates_path.exists():
            candidates = pd.read_csv(candidates_path)
            item_ids = candidates["item_id"].dropna().astype(str).tolist()
            if item_ids:
                run_sampling(config_path, run_dir=run_dir, round_index=2, item_ids=item_ids)
                normalize_run(config_path, run_dir)
                analyze_run(config_path, run_dir)

    plot_run(config_path, run_dir)
    return run_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coordbench", description="CoordBench research benchmark CLI")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("fetch-source-data", help="Download the public OSF source files.")

    prepare_parser = subparsers.add_parser("prepare-human-panels", help="Prepare benchmark-ready human panels.")
    prepare_parser.add_argument("--source-snapshot", default=None, help="Optional source snapshot directory.")

    profile_parser = subparsers.add_parser("profile-dataset", help="Profile the prepared benchmark dataset.")
    profile_parser.add_argument("--prepared-snapshot", default=None, help="Optional prepared snapshot directory.")

    sampling_parser = subparsers.add_parser("run-sampling", help="Run LLM sampling for the selected config.")
    sampling_parser.add_argument("--config", required=True)
    sampling_parser.add_argument("--run-id", default=None)
    sampling_parser.add_argument("--round", type=int, default=1)
    sampling_parser.add_argument(
        "--item-ids",
        default=None,
        help="Optional comma-separated item ids to sample (overrides config item_ids for this call).",
    )

    normalize_parser = subparsers.add_parser("normalize", help="Normalize a run against the human benchmark.")
    normalize_parser.add_argument("--config", required=True)
    normalize_parser.add_argument("--run-id", required=True)
    normalize_parser.add_argument(
        "--allow-unmapped",
        action="store_true",
        help="Treat unmatched answers as unmapped instead of failing (useful for Track B repair/sham surfaces).",
    )

    analyze_parser = subparsers.add_parser("analyze", help="Compute metrics for a run.")
    analyze_parser.add_argument("--config", required=True)
    analyze_parser.add_argument("--run-id", required=True)

    plot_parser = subparsers.add_parser("plot", help="Generate plots for a run.")
    plot_parser.add_argument("--config", required=True)
    plot_parser.add_argument("--run-id", required=True)

    run_all_parser = subparsers.add_parser("run-all", help="Run the complete end-to-end benchmark pipeline.")
    run_all_parser.add_argument("--config", required=True)

    track_b_parser = subparsers.add_parser(
        "track-b",
        help="Track B runner is provided by the Agent package. Install it with: pip install -e Agent",
    )
    track_b_sub = track_b_parser.add_subparsers(dest="track_b_command", required=True)
    track_b_run = track_b_sub.add_parser("run", help="Run Track B via Agent/ integration.")
    track_b_run.add_argument("--config", required=True, help="Benchmark YAML (panel must match baseline).")
    track_b_run.add_argument("--baseline-run", required=True, help="Baseline run id under run_root, or absolute path.")
    track_b_run.add_argument("--track-b-config", default="Agent/config/track_b.example.yaml")
    track_b_run.add_argument("--repair-templates", default="Agent/prompts/repair_templates.yaml")
    track_b_run.add_argument("--tag-map", default="Agent/prompts/tag_to_repair.yaml")
    track_b_run.add_argument("--provider", default=None)
    track_b_run.add_argument("--stub-diagnose", action="store_true")
    track_b_run.add_argument("--diagnosis-max-output-tokens", type=int, default=256)
    track_b_run.add_argument("--repair-round", type=int, default=3)
    track_b_run.add_argument("--sham-round", type=int, default=4)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.verbose)

    if args.command == "fetch-source-data":
        snapshot_dir = fetch_source_data()
        print(snapshot_dir)
        return

    if args.command == "prepare-human-panels":
        source_dir = Path(args.source_snapshot).resolve() if args.source_snapshot else None
        prepared_dir = prepare_human_panels(source_dir)
        print(prepared_dir)
        return

    if args.command == "profile-dataset":
        prepared_dir = Path(args.prepared_snapshot).resolve() if args.prepared_snapshot else None
        profiled = profile_dataset(prepared_dir)
        print(profiled)
        return

    if args.command == "run-sampling":
        run_dir = _resolve_run_dir(args.config, args.run_id) if args.run_id else None
        item_ids = None
        if args.item_ids:
            item_ids = [item.strip() for item in str(args.item_ids).split(",") if item.strip()]
        created = run_sampling(args.config, run_dir=run_dir, round_index=args.round, item_ids=item_ids)
        print(created)
        return

    if args.command == "normalize":
        normalized = normalize_run(
            args.config,
            args.run_id,
            allow_unmapped_override=True if args.allow_unmapped else None,
        )
        print(normalized)
        return

    if args.command == "analyze":
        analyzed = analyze_run(args.config, args.run_id)
        print(analyzed)
        return

    if args.command == "plot":
        plotted = plot_run(args.config, args.run_id)
        print(plotted)
        return

    if args.command == "run-all":
        run_dir = _run_all(args.config)
        print(run_dir)
        return

    if args.command == "track-b":
        if args.track_b_command == "run":
            if run_track_b_agent is None:
                raise RuntimeError("Track B requires Agent package. Install: pip install -e Agent")
            run_dir = run_track_b_agent(
                coordbench_config=args.config,
                baseline_run=args.baseline_run,
                track_b_config=args.track_b_config,
                repair_templates_yaml=args.repair_templates,
                tag_map_yaml=args.tag_map,
                provider=args.provider,
                stub_diagnose=args.stub_diagnose,
                diagnosis_max_output_tokens=args.diagnosis_max_output_tokens,
                repair_round=args.repair_round,
                sham_round=args.sham_round,
            )
            print(run_dir)
            return
        parser.error(f"Unknown track-b command: {args.track_b_command}")

    parser.error(f"Unknown command: {args.command}")


app = main


if __name__ == "__main__":
    main()
