from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def _jsd_map(item_metrics: pd.DataFrame, round_index: int, panel_id: str) -> dict[str, float]:
    m = item_metrics[
        (item_metrics["metric_family"] == "cross_lingual")
        & (item_metrics["round_index"] == int(round_index))
        & (item_metrics["prompt_language"] == "en_vs_zh")
        & (item_metrics["panel_id"] == panel_id)
    ]
    if m.empty:
        return {}
    return dict(zip(m["item_id"].astype(str), m["jsd"].astype(float)))


def write_track_b_report(
    baseline_dir: Path,
    track_dir: Path,
    *,
    panel_id: str,
    baseline_round: int = 1,
    repair_round: int,
    sham_round: int,
) -> Path:
    base_m = pd.read_csv(baseline_dir / "item_metrics.csv")
    track_m = pd.read_csv(track_dir / "item_metrics.csv")
    plan_path = track_dir / "track_b_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.exists() else []

    r1 = _jsd_map(base_m, baseline_round, panel_id)
    rr = _jsd_map(track_m, repair_round, panel_id)
    sr = _jsd_map(track_m, sham_round, panel_id)

    lines: list[str] = [
        "# Track B report",
        "",
        f"- Baseline run: `{baseline_dir.resolve()}` (cross-lingual JSD, round {baseline_round})",
        f"- Track B run: `{track_dir.resolve()}` (repair round {repair_round}, sham round {sham_round})",
        f"- Panel: `{panel_id}`",
        "",
        "| cohort | item_id | repair_template | tag | JSD r1 | JSD repair | Δ repair | JSD sham | Δ sham |",
        "|--------|---------|-----------------|-----|--------|------------|----------|----------|--------|",
    ]

    for row in plan:
        item_id = str(row["item_id"])
        cohort = str(row.get("cohort", ""))
        rt = str(row.get("repair_template", ""))
        tag = str(row.get("primary_tag", ""))
        j1 = r1.get(item_id)
        jr = rr.get(item_id)
        js = sr.get(item_id)
        d_r = None if j1 is None or jr is None else float(jr) - float(j1)
        d_s = None if j1 is None or js is None else float(js) - float(j1)

        def fmt(x: float | None) -> str:
            return "" if x is None else f"{x:.4f}"

        lines.append(
            "| "
            + " | ".join(
                [
                    cohort,
                    item_id,
                    rt,
                    tag,
                    fmt(j1),
                    fmt(jr),
                    fmt(d_r),
                    fmt(js),
                    fmt(d_s),
                ]
            )
            + " |"
        )

    flagged = [r for r in plan if r.get("cohort") == "flagged"]
    if flagged:
        d_rep = [
            float(rr[str(r["item_id"])]) - float(r1[str(r["item_id"])])
            for r in flagged
            if str(r["item_id"]) in rr and str(r["item_id"]) in r1
        ]
        d_sham = [
            float(sr[str(r["item_id"])]) - float(r1[str(r["item_id"])])
            for r in flagged
            if str(r["item_id"]) in sr and str(r["item_id"]) in r1
        ]
        lines.extend(
            [
                "",
                "## Flagged summary (mean ΔJSD vs baseline r1)",
                "",
                f"- Repair arm: **{sum(d_rep) / len(d_rep):.4f}** (n={len(d_rep)})" if d_rep else "- Repair arm: (no complete rows)",
                f"- Sham arm: **{sum(d_sham) / len(d_sham):.4f}** (n={len(d_sham)})" if d_sham else "- Sham arm: (no complete rows)",
                "",
            ]
        )

    out = track_dir / "track_b_report.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out

