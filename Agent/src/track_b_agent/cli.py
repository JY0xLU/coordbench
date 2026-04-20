from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from track_b_agent.audit import audit_serialized_payload, audit_rendered_prompts
from track_b_agent.diagnosis_stub import write_stub_diagnoses
from track_b_agent.flags import TrackBConfig, write_track_b_artifacts
from track_b_agent.repair_manifest import write_repair_manifest
from track_b_agent.templates import load_repair_templates, render_repair_template

app = typer.Typer(help="Light Track B scaffolding (COMP3520 Agent/)")


def run_cli() -> None:
    app()


@app.command()
def flag(
    item_metrics: Path = typer.Option(..., "--item-metrics", exists=True, dir_okay=False),
    out: Path = typer.Option(..., "--out", help="artifacts/track_b/<baseline_run_id>/"),
    config: Path = typer.Option(..., "--config", exists=True),
    panel_id: str | None = typer.Option(None, "--panel-id", help="Optional filter"),
) -> None:
    """Generate flagged_items.json, unflagged_controls.json, track_b_manifest.json."""
    cfg = TrackBConfig.from_yaml(config)
    path = write_track_b_artifacts(out, item_metrics, cfg, panel_id=panel_id)
    typer.echo(path)


@app.command("diagnose-stub")
def diagnose_stub(
    out: Path = typer.Option(..., "--out", exists=True, file_okay=False),
) -> None:
    """Write diagnosis/*.json with T_UNK for each flagged item."""
    n = write_stub_diagnoses(out)
    typer.echo(f"wrote {n} stub diagnoses under {out / 'diagnosis'}")


@app.command("write-repair-manifest")
def write_repair_manifest_cmd(
    out: Path = typer.Option(..., "--out", exists=True, file_okay=False),
    tag_map: Path = typer.Option(..., "--tag-map", exists=True),
) -> None:
    p = write_repair_manifest(out, tag_map)
    typer.echo(p)


@app.command("run")
def run_integrated(
    coordbench_config: Path = typer.Option(..., "--coordbench-config", exists=True, dir_okay=False),
    baseline_run: str = typer.Option(
        ...,
        "--baseline-run",
        help="Baseline run id (under config run_root) OR an absolute path to the baseline run directory.",
    ),
    track_b_config: Path = typer.Option(Path("config/track_b.example.yaml"), "--track-b-config", exists=True, dir_okay=False),
    repair_templates: Path = typer.Option(Path("prompts/repair_templates.yaml"), "--repair-templates", exists=True, dir_okay=False),
    tag_map: Path = typer.Option(Path("prompts/tag_to_repair.yaml"), "--tag-map", exists=True, dir_okay=False),
    provider: str | None = typer.Option(None, "--provider", help="Force provider name (must exist in coordbench config)."),
    stub_diagnose: bool = typer.Option(False, "--stub-diagnose", help="Skip LLM diagnosis; use T_UNK → R_COORD."),
    diagnosis_max_output_tokens: int = typer.Option(256, "--diagnosis-max-output-tokens"),
    repair_round: int = typer.Option(3, "--repair-round"),
    sham_round: int = typer.Option(4, "--sham-round"),
) -> None:
    """Integrated Track B runner (runs sampling + normalize + analyze + report)."""
    from track_b_agent.integrated.pipeline import run_track_b

    # Make prompt/config defaults resolve relative to Agent/ when invoked from repo root.
    agent_root = Path(__file__).resolve().parents[2]
    def _resolve(p: Path) -> Path:
        return p if p.is_absolute() else (agent_root / p).resolve()

    run_dir = run_track_b(
        coordbench_config=coordbench_config,
        baseline_run=baseline_run,
        track_b_config=_resolve(track_b_config),
        repair_templates_yaml=_resolve(repair_templates),
        tag_map_yaml=_resolve(tag_map),
        provider=provider,
        stub_diagnose=stub_diagnose,
        diagnosis_max_output_tokens=diagnosis_max_output_tokens,
        repair_round=repair_round,
        sham_round=sham_round,
    )
    typer.echo(run_dir)


@app.command("audit-payload")
def audit_payload(
    payload: str = typer.Argument(
        ...,
        help="Path to JSON file, or '-' for stdin",
    ),
) -> None:
    """Allowlist + blacklist audit on a JSON payload."""
    if payload == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(payload).read_text(encoding="utf-8")
    obj = json.loads(raw)
    allow_bad, bl_bad = audit_serialized_payload(obj)
    if allow_bad:
        typer.echo(f"ALLOWLIST_VIOLATION: extra keys {allow_bad}", err=True)
    if bl_bad:
        typer.echo(f"BLACKLIST_HIT: {bl_bad}", err=True)
    if allow_bad or bl_bad:
        raise typer.Exit(code=1)
    typer.echo("ok")


@app.command("preview-template")
def preview_template(
    template_id: str = typer.Argument(...),
    prompt_lang: str = typer.Option("en", "--lang"),
    yaml_path: Path = typer.Option(..., "--yaml", exists=True),
) -> None:
    """Smoke-render a repair template (dummy contexts)."""
    tpls = load_repair_templates(yaml_path)
    s, u = render_repair_template(
        template_id,
        prompt_language=prompt_lang,
        templates=tpls,
        item_text_en="Name a city",
        item_text_zh="说出一座城市",
        answer_language="English",
        context_en="from the UK",
        context_zh="来自英国",
    )
    hits = audit_rendered_prompts(s, u)
    if hits:
        typer.echo(f"BLACKLIST_HIT in rendered prompts: {hits}", err=True)
        raise typer.Exit(code=1)
    typer.echo("=== system ===\n" + s + "\n=== user ===\n" + u)


if __name__ == "__main__":
    run_cli()
