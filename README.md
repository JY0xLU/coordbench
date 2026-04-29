<p align="center">
  <img src="assets/coordbench-logo.svg" alt="coordbench logo" width="140">
</p>

<h1 align="center">coordbench</h1>

<p align="center">
  <strong>一个用于评估 LLM 跨语言默契协调能力的可复现实验管线。</strong><br>
  它把人类协调游戏数据、英中双语提示、答案归一化和稳健性指标放进同一条可追踪流水线里。
</p>

<p align="center">
  <a href="README.en.md">English</a>
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
  <img alt="Languages" src="https://img.shields.io/badge/prompts-EN%20%2F%20ZH-0F766E?style=flat-square">
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-blue?style=flat-square"></a>
  <img alt="Last commit" src="https://img.shields.io/github/last-commit/JY0xLU/coordbench/main?style=flat-square">
</p>

<p align="center">
  <img src="assets/coordbench-flow.svg" alt="coordbench workflow" width="100%">
</p>

## 它解决什么问题

很多 LLM benchmark 关心“答得对不对”，但协调问题更微妙：当没有明确正确答案时，模型能不能和目标群体想到同一个默认答案？换句话说，它是不是懂那种“大家心照不宣会选什么”的默契。

`coordbench` 关注这个问题的小切口：在英中双语提示下，比较不同模型在 tacit coordination games 里的回答分布、跨语言一致性，以及和人类参考分布的贴近程度。

它不是一个只跑一次的 notebook，而是一套尽量可复现、可审计、可继续扩展的实验管线。小心翼翼，但不装神秘。:)

## 核心能力

| 模块 | 做什么 |
| --- | --- |
| 数据获取 | 从 OSF 项目拉取公开源数据，并生成 source snapshot |
| 人类 panel | 重建 benchmark-ready human panels、分布和题目清单 |
| 双语采样 | 支持 EN / ZH 匹配提示，并固定 answer language |
| 答案归一化 | 结合 canonical answer、alias、大小写/空格/标点折叠处理模型输出 |
| 双轨指标 | 同时计算跨语言协调轨道和 human-alignment 轨道 |
| Round 2 | 根据 mismatch 候选题生成二轮 re-coordination |
| Track B | 对 baseline run 自动 flag、诊断、repair/sham 重采样并生成报告 |

## 快速开始

```bash
git clone https://github.com/JY0xLU/coordbench.git
cd coordbench
pip install -e .[dev]
```

从 `.env.example` 创建 `.env`，按需填入模型 provider：

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

运行默认英中 benchmark：

```bash
coordbench run-all --config configs/study2_british_en_zh.yaml
```

## 常用命令

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

标准流程是：

```text
fetch-source-data -> prepare-human-panels -> profile-dataset
-> run-sampling -> normalize -> analyze -> plot
```

如果只想一口气跑完采样到图表，用 `run-all` 就行。

## Track B：诊断与修复实验

Track B 的集成实现放在 `Agent/` 目录里。它会基于已经完成 `normalize + analyze` 的 baseline run，自动执行：

```text
flag -> LLM diagnosis -> repair/sham resampling -> normalize -> analyze -> report
```

安装 Agent 包：

```bash
pip install -e Agent
```

运行 Track B：

```bash
coordbench track-b run \
  --config configs/study2_british_en_zh.yaml \
  --baseline-run <run_id_or_path>
```

没有诊断 API 时，可以先用占位诊断跑通流程：

```bash
coordbench track-b run \
  --config configs/study2_british_en_zh.yaml \
  --baseline-run <run_id> \
  --stub-diagnose
```

日志会显示类似 `[Track B] phase i/6 ... | overall xx%` 的进度。如果它安静了一会儿，多半是在等某次模型 API 返回，不一定是挂了。

## 输出结构

准备后的数据会写到：

```text
data/prepared/<snapshot_id>/
```

典型文件包括：

```text
participant_responses.csv
human_distributions.csv
panel_items.csv
panel_summary.csv
dataset_inventory.json
selection_report.md
benchmark_manifest.json
```

每次实验 run 会写到：

```text
artifacts/runs/<run_id>/
```

典型产物包括：

```text
run_manifest.json
raw_generations.jsonl
normalized_outputs.csv
unresolved_queue.csv
cell_completeness.csv
coord_cell_completeness.csv
item_metrics.csv
summary_metrics.json
bootstrap_intervals.csv
round2_candidates.csv
plots/
```

整理后的实验报告和历史结果放在 `results/`。命名规则见 [results/README.md](results/README.md)。

## 仓库结构

| 路径 | 内容 |
| --- | --- |
| `src/coordbench/` | 主 benchmark 包和 CLI |
| `Agent/` | Track B agent / repair pipeline |
| `configs/` | benchmark、provider、采样配置 |
| `data/` | 源数据、alias、prepared panels |
| `scripts/` | 长实验 runner、监控和调试脚本 |
| `tests/` | 单元测试和集成测试 |
| `docs/` | 数据风险、proposal、更新记录 |
| `results/` | 整理后的实验结果 |

## 方法口径

`coordbench` 目前默认关注：

- 默认 panel：`study2_british_within`
- 默认 prompt languages：`en`, `zh`
- 默认 answer language：`English`
- 默认 normalization：`allow_unmapped: false`
- Round-2 trigger：
  - `cross_lingual_top1_mismatch`
  - `human_top1_mismatch`
  - `either_top1_mismatch`

核心指标分两条轨道：

- Cross-lingual coordination：基于 `coord_answer_key`，更关注同一模型在不同语言提示下是否走向同一答案。
- Human alignment：基于 human-mapped `canonical_answer`，更关注模型回答是否贴近人类参考分布。

## 开发

```bash
pytest -q
```

如果你改了包名、CLI、配置或 Track B 集成，建议至少跑：

```bash
pytest -q
python -m coordbench --help
coordbench --help
```

## 数据来源

- OSF project: https://osf.io/fv47d/
- Perez-Zapata et al., *Three International Studies on Pure Coordination Games*

## Star History

<a href="https://www.star-history.com/#JY0xLU/coordbench&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=JY0xLU/coordbench&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=JY0xLU/coordbench&type=Date" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=JY0xLU/coordbench&type=Date" />
  </picture>
</a>
