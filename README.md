# CoordBench (COMP3520 Project)

CoordBench is a reproducible benchmark pipeline for evaluating cross-lingual robustness of tacit coordination in LLMs, with human-reference metrics.

It supports:
- OSF source data fetch + panel preparation
- EN/ZH matched prompting with fixed answer language
- answer normalization against human canonical distributions
- dual-track metrics:
  - cross-lingual coordination from `coord_answer_key` (case/space/punctuation folded + alias harmonized, not gated by human/fuzzy mapping)
  - human-alignment from human-mapped `canonical_answer`
- round-2 re-coordination candidate generation

**Track B（Agent 集成流程）**：Track B 的集成实现放在 `Agent/` 目录内（包名 `track-b-agent`），主 `coordbench track-b ...` 命令会在安装 Agent 包后调用它。在已完成 **normalize + analyze** 的 baseline 运行上，自动 flag → LLM 诊断 → repair/sham 双臂重采样（`round_index` 默认 3 / 4）→ `normalize` → `analyze` → `track_b_report.md`。日志里会以 **`[Track B] phase i/6 … | overall xx%`** 标出当前阶段与子步进度；若长时间没有新行，多半是在等单次 API（诊断或某个采样请求）返回。

```bash
coordbench track-b run --config configs/study2_british_en_zh.yaml --baseline-run <run_id_or_path>
# 无诊断 API时可用占位标签：
coordbench track-b run --config configs/study2_british_en_zh.yaml --baseline-run <run_id> --stub-diagnose
```

双臂的每格样本数取自配置里的 **`sampling.round2_samples`**（round 3/4 与 round 2 共用该期望值）。可选：`Agent/` 下仍有 `track-b-agent` 分步脚手架与 [`Agent/agent_plan.md`](Agent/agent_plan.md)。

## Quick Start

1. Install:

```bash
pip install -e .[dev]
```

2. Configure `.env` from `.env.example`:
- `OPENAI_API_KEY`, `OPENAI_MODEL`
- `GEMINI_API_KEY`, `GEMINI_MODEL`
- `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`
- `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL`

3. Run full pipeline with default benchmark config:

```bash
coordbench run-all --config configs/study2_british_en_zh.yaml
```

## Core CLI

```bash
coordbench fetch-source-data
coordbench prepare-human-panels
coordbench profile-dataset
coordbench run-sampling --config configs/study2_british_en_zh.yaml
coordbench normalize --config configs/study2_british_en_zh.yaml --run-id <run_id>
coordbench analyze --config configs/study2_british_en_zh.yaml --run-id <run_id>
coordbench plot --config configs/study2_british_en_zh.yaml --run-id <run_id>
coordbench run-all --config configs/study2_british_en_zh.yaml
coordbench track-b run --config configs/study2_british_en_zh.yaml --baseline-run <run_id_or_path>
```

## Standard Workflow

1. `fetch-source-data`
2. `prepare-human-panels`
3. `profile-dataset`
4. `run-sampling`
5. `normalize`
6. `analyze`
7. `plot`

Or use `run-all` to run 4–7 end-to-end.


## Config Conventions

- Default panel: `study2_british_within`
- Default prompt languages: `en`, `zh`
- Default answer language: `English`
- Normalization default: `allow_unmapped: false`
- Round-2 trigger supports:
  - `cross_lingual_top1_mismatch`
  - `human_top1_mismatch`
  - `either_top1_mismatch`

## Repository Layout

- `src/coordbench/`: package source code
- `tests/`: unit/integration tests
- `configs/`: benchmark and provider configs
- `scripts/`: experiment runners and monitors
- `scripts/debug/`: ad-hoc debugging scripts
- `tools/`: one-off utility scripts
- `docs/proposal/`: proposal files
- `docs/risks/`: risk/method notes
- `docs/updates/`: repository update logs

## Output Layout

### Prepared data

`data/prepared/<snapshot_id>/`:
- `participant_responses.csv`
- `human_distributions.csv`
- `panel_items.csv`
- `panel_summary.csv`
- `dataset_inventory.json`
- `selection_report.md`
- `benchmark_manifest.json`

### Run artifacts

`artifacts/runs/<run_id>/`:
- `run_manifest.json`
- `raw_generations.jsonl`
- `normalized_outputs.csv`
- `unresolved_queue.csv`
- `cell_completeness.csv` (human-alignment track)
- `coord_cell_completeness.csv` (cross-lingual track)
- `item_metrics.csv`
- `summary_metrics.json`
- `bootstrap_intervals.csv`
- `round2_candidates.csv`
- `plots/`

### Experiment reports

`results/` is organized by experiment type:
- `results/previous/` (archived historical results by experiment type)
- `results/runs_s50/` (curated post-code-update 50-sample run folders)

See `results/README.md` for naming conventions.

## Script Entry Points

- Full multi-model experiments: `scripts/run_new_models_full_experiments.py`
- Single full experiment: `scripts/run_one_full_experiment.py`
- Universal full experiments: `scripts/run_universal_full_experiments.py`
- Stability probe: `scripts/run_model_stability_probe.py`
- Concurrency sweep: `scripts/run_universal_concurrency_sweep.py`
- Monitoring: `scripts/watch_full_experiment_status.py`, `scripts/monitor_token_usage.py`

## Tests

```bash
pytest -q
```

## Source Data

- OSF project: https://osf.io/fv47d/
- Perez-Zapata et al., *Three International Studies on Pure Coordination Games*
