from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from coordbench.config import load_config

LOGGER = logging.getLogger(__name__)


def plot_run(config_path: str | Path, run_id: str | Path) -> Path:
    config = load_config(config_path)
    run_dir = Path(run_id)
    if not run_dir.is_absolute():
        run_dir = config.outputs.run_root / str(run_id)
    item_metrics = pd.read_csv(run_dir / "item_metrics.csv")
    summary = pd.read_json(run_dir / "summary_metrics.json")
    plots_dir = run_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    cross = item_metrics[item_metrics["metric_family"] == "cross_lingual"].copy()
    if not cross.empty:
        plt.figure(figsize=(12, 6))
        cross["label"] = cross["provider"] + ":" + cross["model"] + ":r" + cross["round_index"].astype(str)
        for label, subset in cross.groupby("label"):
            plt.plot(subset["item_number"], subset["jsd"], marker="o", label=label)
        plt.title("Per-item EN vs ZH JSD")
        plt.xlabel("Item Number")
        plt.ylabel("JSD")
        plt.legend(fontsize=8)
        plt.tight_layout()
        plt.savefig(plots_dir / "per_item_jsd.png", dpi=200)
        plt.savefig(plots_dir / "per_item_jsd.pdf")
        plt.close()

        aggregate = summary[summary["metric_family"] == "cross_lingual"].copy()
        aggregate["label"] = (
            aggregate["provider"]
            + ":"
            + aggregate["model"]
            + ":r"
            + aggregate["round_index"].astype(str)
        )

        plt.figure(figsize=(10, 5))
        plt.bar(aggregate["label"], aggregate["mean_top1_match"])
        plt.title("EN vs ZH Top-1 Match")
        plt.ylabel("Mean top-1 match")
        plt.xticks(rotation=25, ha="right")
        plt.tight_layout()
        plt.savefig(plots_dir / "top1_agreement.png", dpi=200)
        plt.savefig(plots_dir / "top1_agreement.pdf")
        plt.close()

        plt.figure(figsize=(10, 5))
        plt.bar(aggregate["label"], aggregate["mean_flip_rate"])
        plt.title("Focal-point Flip Rate")
        plt.ylabel("Mean flip rate")
        plt.xticks(rotation=25, ha="right")
        plt.tight_layout()
        plt.savefig(plots_dir / "flip_rate.png", dpi=200)
        plt.savefig(plots_dir / "flip_rate.pdf")
        plt.close()

        consensus = (
            cross.groupby(["consensus_bucket", "provider", "model", "round_index"])
            .agg(
                mean_jsd=("jsd", "mean"),
                mean_top1_match=("top1_match", "mean"),
                mean_flip_rate=("flip_rate", "mean"),
            )
            .reset_index()
        )
        if not consensus.empty:
            fig, ax = plt.subplots(figsize=(10, 5))
            consensus["label"] = consensus["provider"] + ":" + consensus["model"]
            for label, subset in consensus.groupby("label"):
                ax.plot(subset["consensus_bucket"], subset["mean_jsd"], marker="o", label=label)
            ax.set_title("Consensus Bucket vs Cross-lingual JSD")
            ax.set_ylabel("Mean JSD")
            ax.legend(fontsize=8)
            fig.tight_layout()
            fig.savefig(plots_dir / "consensus_bucket.png", dpi=200)
            fig.savefig(plots_dir / "consensus_bucket.pdf")
            plt.close(fig)

            fig, axes = plt.subplots(1, 3, figsize=(16, 5))
            for label, subset in consensus.groupby("label"):
                axes[0].plot(subset["consensus_bucket"], subset["mean_jsd"], marker="o", label=label)
                axes[1].plot(subset["consensus_bucket"], subset["mean_top1_match"], marker="o", label=label)
                axes[2].plot(subset["consensus_bucket"], subset["mean_flip_rate"], marker="o", label=label)
            axes[0].set_title("Bucket vs JSD")
            axes[0].set_ylabel("Mean JSD")
            axes[1].set_title("Bucket vs Top-1 Match")
            axes[1].set_ylabel("Mean Top-1 Match")
            axes[2].set_title("Bucket vs Flip Rate")
            axes[2].set_ylabel("Mean Flip Rate")
            for axis in axes:
                axis.set_xlabel("Consensus Bucket")
            axes[0].legend(fontsize=8)
            fig.tight_layout()
            fig.savefig(plots_dir / "consensus_bucket_metrics.png", dpi=200)
            fig.savefig(plots_dir / "consensus_bucket_metrics.pdf")
            plt.close(fig)

        if cross["round_index"].nunique() > 1:
            round_compare = (
                cross.groupby(["provider", "model", "round_index"])
                .agg(mean_jsd=("jsd", "mean"), mean_flip=("flip_rate", "mean"))
                .reset_index()
            )
            round_compare["label"] = round_compare["provider"] + ":" + round_compare["model"]
            fig, axes = plt.subplots(1, 2, figsize=(12, 5))
            for label, subset in round_compare.groupby("label"):
                axes[0].plot(subset["round_index"], subset["mean_jsd"], marker="o", label=label)
                axes[1].plot(subset["round_index"], subset["mean_flip"], marker="o", label=label)
            axes[0].set_title("Round Comparison: JSD")
            axes[0].set_xlabel("Round")
            axes[0].set_ylabel("Mean JSD")
            axes[1].set_title("Round Comparison: Flip Rate")
            axes[1].set_xlabel("Round")
            axes[1].set_ylabel("Mean flip rate")
            axes[0].legend(fontsize=8)
            fig.tight_layout()
            fig.savefig(plots_dir / "round_comparison.png", dpi=200)
            fig.savefig(plots_dir / "round_comparison.pdf")
            plt.close(fig)

    LOGGER.info("Wrote plots into %s", plots_dir)
    return run_dir
