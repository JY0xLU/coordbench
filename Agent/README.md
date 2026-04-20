# Track B Agent（集成 + 轻量脚手架）

本目录实现两部分：

- **集成版 Track B（推荐）**：一条命令完成 baseline→flag→诊断→repair/sham 采样→normalize→analyze→`track_b_report.md`。
- **轻量脚手架（旧）**：从 `item_metrics.csv` 生成 `flagged_items.json` / `unflagged_controls.json`、审计 payload、模板 YAML 等分步工具。

说明：
- 集成版会调用主包 `coordbench` 的采样/normalize/analyze 能力。
- 轻量脚手架仅产出清单与模板，适合人工/脚本衔接。

## 安装

**方式 A（推荐，与 CoordBench 共用依赖）**：根目录已有 venv 且已 `pip install -e .`（coordbench）时，依赖已含 `pandas` / `pyyaml` / `typer`，只需：

```bash
cd Agent
pip install -e . --no-build-isolation   # 若网络受限，可先确保本机有 setuptools
```

**方式 B（仅跑测试，不安装 entrypoint）**：

```bash
PYTHONPATH=Agent/src python -m pytest Agent/tests -q
```

（需在已安装 `pandas`, `pyyaml`, `typer`, `pytest` 的环境中执行。）

## 配置

复制并编辑：

```bash
cp config/track_b.example.yaml config/track_b.yaml
```

## 一条命令跑 Track B（集成版，推荐）

你需要先有一个已完成 `normalize + analyze` 的 baseline run 目录（里面有 `item_metrics.csv`）。

### 方式 1：通过主包 CLI（会调用本 Agent 实现）

```bash
cd ..
pip install -e .[dev]
pip install -e Agent --no-build-isolation

coordbench track-b run \
  --config configs/study2_deepseek_s50.yaml \
  --baseline-run /ABS/PATH/TO/baseline_run_dir \
  --provider deepseek
```

### 方式 2：直接用 Agent CLI（更明确）

```bash
track-b-agent run \
  --coordbench-config ../configs/study2_deepseek_s50.yaml \
  --baseline-run /ABS/PATH/TO/baseline_run_dir \
  --provider deepseek \
  --track-b-config config/track_b.example.yaml \
  --repair-templates prompts/repair_templates.yaml \
  --tag-map prompts/tag_to_repair.yaml
```

不想打诊断 API 时加 `--stub-diagnose`。

## 常用命令（轻量脚手架）

```bash
# 从某次 A 轨 run 的 item_metrics.csv 生成 flag + unflagged 清单
track-b-agent flag \
  --item-metrics ../artifacts/runs/20260412T141541Z/item_metrics.csv \
  --out ../artifacts/track_b/20260412T141541Z \
  --config config/track_b.example.yaml

# 对一段将发给 LLM 的 JSON 做黑名单扫描（stdin 或 --file）
echo '{"item_text_en":"Name a city"}' | track-b-agent audit-payload -

# 为每个 flagged item 写入占位 diagnosis（--no-llm，全 T_UNK，便于打通目录结构）
track-b-agent diagnose-stub --out ../artifacts/track_b/20260412T141541Z
```

## 目录结构

| 路径 | 说明 |
|------|------|
| `agent_plan.md` | 与 `docs/` 同步的设计说明（以本文件为 Agent 侧主副本时可自行对齐） |
| `config/track_b.example.yaml` | `max_flagged_items`、`unflagged_control_count`、规则开关 |
| `prompts/repair_templates.yaml` | `R_SEM` / `R_FMT` / `R_COORD` / `R_SHAM` |
| `prompts/tag_to_repair.yaml` | tag → repair 模板 ID |
| `src/track_b_agent/` | Python 包 |

## 与 CoordBench 主仓库

- **Baseline 口径**：常量 `TRACK_B_BASELINE = track_a_round1_only`（见 `constants.py`），写入 `track_b_manifest.json`。
- 模板占位符与 `coordbench.prompts.build_prompt_messages` 对齐；真正联调时可在 `coordbench` 中加 `track_b` 分支或单独 runner 读取本目录 YAML。

## 实验结果汇总（DeepSeek Track B）

完整说明、解读与历史多次重复跑对照见仓库根目录 **[`TRACK_B_AGENT_SUMMARY.md`](../TRACK_B_AGENT_SUMMARY.md)**。下表为与 Agent 集成版直接相关的若干次 run（repair=round 3，sham=round 4，指标为 cross-lingual JSD，flagged 均值 Δ相对 baseline round 1）。

| Run 目录 | Baseline | Flagged mean ΔJSD (repair) | Flagged mean ΔJSD (sham) | 备注 |
|----------|----------|----------------------------|--------------------------|------|
| `artifacts/runs/track_b_20260414T090524Z` | `deepseek-v3.2_20260412T141541Z` | -0.1773 | +0.0913 | 首次完整跑通 |
| `artifacts/runs/track_b_20260414T092927Z` | 同上 | -0.1773 | +0.0913 | 可重复性 rep1 |
| `artifacts/runs/track_b_20260414T093001Z` | 同上 | **-0.4564** | +0.0913 | rep2；`item_12` 诊断为 `R_SEM` 时改进更大 |
| `artifacts/runs/track_b_20260414T102304Z` | `deepseek-v3_20260412T121754Z` | -0.2192 | +0.0495 | 换 v3 基线对照 |
| `artifacts/runs/track_b_20260414T155044Z` | `deepseek-v3.2_20260412T141541Z` | **-0.4564** | +0.0913 | 代码迁入 `Agent/integrated` 后复跑；采样多来自磁盘缓存，诊断为实时 API |

每次 run 下的 **`track_b_report.md`** 为逐题 JSD 与模板/tag 明细。
