<p align="center">
  <img src="assets/coordbench-gpt-hero.png" alt="coordbench hero" width="100%">
</p>

<h1 align="center">coordbench</h1>

<p align="center">
  <strong>A reproducible benchmark pipeline for cross-lingual tacit coordination in LLMs.</strong><br>
  Human coordination distributions, EN/ZH prompts, answer normalization, and dual-track metrics in one auditable workflow.
</p>

<p align="center">
  <a href="README.md">中文</a>
  ·
  <a href="https://github.com/JY0xLU/coordbench">GitHub</a>
  ·
  <a href="https://osf.io/fv47d/">OSF source data</a>
</p>

<p align="center">
  <a href="https://github.com/JY0xLU/coordbench/stargazers"><img alt="GitHub stars" src="https://img.shields.io/github/stars/JY0xLU/coordbench?style=social"></a>
  <a href="https://github.com/JY0xLU/coordbench/network/members"><img alt="GitHub forks" src="https://img.shields.io/github/forks/JY0xLU/coordbench?style=social"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="Pipeline" src="https://img.shields.io/badge/pipeline-reproducible-10B981?style=flat-square">
  <img alt="Prompts" src="https://img.shields.io/badge/prompts-EN%20%2F%20ZH-0F766E?style=flat-square">
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-blue?style=flat-square"></a>
  <img alt="Last commit" src="https://img.shields.io/github/last-commit/JY0xLU/coordbench/main?style=flat-square">
</p>

## What It Solves

Most LLM benchmarks ask whether a model gives the correct answer. Tacit coordination games are different: when there is no single correct answer, can a model choose the answer that a target group would naturally converge on?

`coordbench` turns that question into a reproducible benchmark pipeline. It runs the same coordination items under English and Chinese prompts while fixing the required answer language to English, then evaluates two separate axes:

- **Human alignment:** whether model answer distributions match human focal-point distributions.
- **Cross-lingual stability:** whether the same model preserves its focal-point distribution when only the prompt language changes.

The result is not a one-off notebook. It is a rerunnable, inspectable, and extensible research tool for comparing model behavior.

## Final Report Takeaways

The finalized analysis evaluates **17 Round 1 model runs** on the `study2_british_within` panel, with **15 items x 2 prompt languages x 50 samples** for each complete run.

- **No model wins on both axes.** `mimo-v2-pro` is the most cross-lingually stable model, while `gemini-2.5-flash` is closest to the human reference distribution.
- **Human-likeness and stability are distinct capabilities.** A model can be stable across English/Chinese prompts while still being far from human focal points, or human-like under one prompt language while drifting under the other.
- **Round 2 helps, but unevenly.** On flagged mismatch items, Round 2 restores top-1 agreement for **14/31** item-model pairs and lowers JSD for **21/31** pairs.
- **The final report corrects an earlier slide typo.** `mimo-v2-pro` has mean cross-lingual JSD `0.020`, not `0.20`.

## Method Overview

<p align="center">
  <img src="assets/pipeline-overview-original.jpeg" alt="coordbench bilingual prompting and evaluation pipeline" width="88%">
</p>

The key design choice is to run the same coordination items under English and Chinese instructions while requiring English answers in both conditions. This puts EN/ZH outputs into the same canonical answer space and avoids conflating instruction-language effects with output-language effects.

The pipeline keeps two metric tracks separate:

- **Human-vs-model alignment:** model distribution vs. human reference distribution.
- **EN-vs-ZH stability:** English-prompt model distribution vs. Chinese-prompt model distribution.

Round 2 is triggered only for items where Round 1 shows a cross-lingual top-1 mismatch, testing whether a lightweight retry can repair focal-answer drift.

## Results

### Round 1: Cross-Lingual Stability

<p align="center">
  <img src="assets/round1-cross-lingual-stability-original.png" alt="Round 1 cross-lingual stability results" width="95%">
</p>

Lower JSD means the English- and Chinese-prompt answer distributions are closer. Higher top-1 match means both prompt languages select the same most frequent canonical answer. `mimo-v2-pro`, `mimo-v2-omni`, and the MiniMax M2.7 family form the most stable tier; `qwen3.5-plus`, `gpt-5.4`, and `glm-4-flashx` show much larger drift.

### Round 1: Human Alignment

<p align="center">
  <img src="assets/round1-human-alignment-original.png" alt="Round 1 human alignment results" width="95%">
</p>

Human-alignment JSD compares model output distributions with the same British-within human reference distribution. `gemini-2.5-flash` is closest to humans under both prompt conditions, but it is not the most cross-lingually stable model.

### Round 2: Recovery Diagnostics

<p align="center">
  <img src="assets/round2-recovery-share-original.png" alt="Round 2 recovery share by model" width="95%">
</p>

<p align="center">
  <img src="assets/round2-jsd-candidates-original.png" alt="Round 1 versus Round 2 JSD on candidate items" width="95%">
</p>

Round 2 is a lightweight retry on each model's own mismatch candidate items. It often reduces distributional drift, but it does not reliably restore the same top answer for every model family.

## Features

| Module | Purpose |
| --- | --- |
| Source data | Fetch public OSF data and create source snapshots |
| Human panels | Prepare benchmark-ready human panels and distributions |
| Bilingual sampling | Run EN/ZH matched prompts with fixed answer language |
| Normalization | Map model outputs through canonical answers, aliases, and folded surface forms |
| Dual metrics | Keep human alignment separate from cross-lingual stability |
| Round 2 | Generate re-coordination candidates from mismatch triggers |
| Track B | Flag, diagnose, repair/sham resample, re-normalize, re-analyze, and report |

## Quick Start

```bash
git clone https://github.com/JY0xLU/coordbench.git
cd coordbench
pip install -e .[dev]
```

Create `.env` from `.env.example` and fill the providers you need:

```text
OPENAI_API_KEY=...
OPENAI_MODEL=...
GEMINI_API_KEY=...
GEMINI_MODEL=...
DEEPSEEK_API_KEY=...
DEEPSEEK_MODEL=...
ANTHROPIC_AUTH_TOKEN=...
ANTHROPIC_BASE_URL=...
ANTHROPIC_MODEL=...
```

Run the default EN/ZH benchmark:

```bash
coordbench run-all --config configs/study2_british_en_zh.yaml
```

## Common Commands

```bash
coordbench fetch-source-data
coordbench prepare-human-panels
coordbench profile-dataset
coordbench run-sampling --config configs/study2_british_en_zh.yaml
coordbench normalize --config configs/study2_british_en_zh.yaml --run-id <run_id>
coordbench analyze --config configs/study2_british_en_zh.yaml --run-id <run_id>
coordbench plot --config configs/study2_british_en_zh.yaml --run-id <run_id>
coordbench run-all --config configs/study2_british_en_zh.yaml
```

## Output Layout

Prepared data usually lives under `data/prepared/<snapshot_id>/`:

- `panel_items.csv`: benchmark items, prompt text, panel metadata, and language variants.
- `participant_responses.csv`: cleaned individual human responses.
- `human_distributions.csv`: aggregated human focal-point distributions used as the human-alignment reference.
- `panel_summary.csv`, `dataset_inventory.json`, `selection_report.md`, `benchmark_manifest.json`: audit and provenance files.

Run artifacts usually live under `artifacts/runs/<run_id>/`:

- `raw_generations.jsonl`: raw model responses.
- `normalized_outputs.csv`: canonicalized answers after alias mapping.
- `item_metrics.csv`: item-level JSD, TVD, top-1 match, flip rate, and Spearman diagnostics.
- `summary_metrics.json`: model-level summaries.
- `round2_candidates.csv`: items selected for Round 2 retry.
- `plots/`: generated analysis figures.

## Repository Layout

```text
src/coordbench/      Python package and CLI implementation
configs/             benchmark/provider YAML configs
data/                source and prepared human-panel data
artifacts/           run outputs, caches, logs, and plots
results/             curated results and historical reports
scripts/             experiment runners and monitoring scripts
tools/               one-off aggregation and plotting utilities
tests/               unit and integration tests
assets/              README logo, diagrams, and result figures
```

## Tests

```bash
pytest -q
```

## Source Data

- OSF project: <https://osf.io/fv47d/>
- Human coordination source: Perez-Zapata et al., *Three International Studies on Pure Coordination Games*

