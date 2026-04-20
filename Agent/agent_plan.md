# 轻量 Track B 实施计划（Light Track B, v2.1）

**实现状态（本目录）**：`track_b_agent` 包已落地 **flag 选取**、**确定性截断**、**unflagged 对照**、**stub diagnosis**、**repair_manifest**、**审计（allowlist + 黑名单）**、**YAML 模板**。与 `coordbench run_sampling` 的 **自动联调** 仍待接（方案 B：独立 run + 合并分析）。详见 `README.md`。

**定位**：在 **轨道 A（冻结主实验）** 完成后，对 **flagged items** 做 **固定 taxonomy 诊断标签**、**模板化 repair prompt**、**受控前后对照**，并 **全程不向模型泄露人类回答分布或众数答案**。

**非目标**：不替代主实验；不把归一化全权交给 LLM；不引入复杂 multi-agent 编排（planner/critic/memory 等）。

---

## 1. 背景与成功标准

### 1.1 与现有代码的关系

| 现有能力 | 与 Track B 的关系 |
|----------|-------------------|
| `analyze_run` → `item_metrics.csv`、`round2_candidates.csv` | **Flag 来源**（可扩展规则） |
| `run_sampling` round 1/2、`build_prompt_messages` | **基线 vs 额外 repair 轮** 需扩展或并行 config |
| `normalize` / `analyze` / `plot` | **前后指标** 复用；需能区分 `experiment_arm` 或 `round_index` |
| `docs/risks/RAW_DATA_AND_RISKS.md` | 归一化与协议风险，Track B 不得放宽「不泄露」约束 |

### 1.2 成功标准（验收）

1. **协议**：Repair 与 Diagnosis 的 **所有 LLM 输入** 经脚本或 checklist 审计，**不得包含** `human_distributions`、human top-1、频率表、canonical 排序列表等。
2. **可复现**：Flag 规则、tag 枚举、repair 模板 ID、随机种子、采样数 **写入 manifest**。
3. **可对照**：同一 `item_id`、同一 provider/model/decoding 下，**baseline**（A 轨 round1-only）、**repair**、**sham** 三臂可并列比较；**unflagged** 对照题用于分离「重采样」与「repair 内容」效应。
4. **可写作**：自动生成 `track_b_report.md`：flagged 列表、tag 分布、模板使用频率、按 item 的前后差值（及可选 bootstrap）。

---

## 2. 范围（In / Out of Scope）

### 2.1 In Scope（轻量 B）

- 从 **已完成轨道 A 的 run**（或约定好的 baseline run）读取指标，生成 **flagged item 集合**（含 §3.2 确定性截断）。
- **Diagnosis**：对 flagged items 产出 **固定集合内** 的 tags + 短证据（可选：一次 LLM 调用，严格 schema）。
- **Repair + 对照**：**MVP 必含**（与 §7 一致）：① 对 **flagged** 题跑 **repair** 模板；② 对同一批 flagged 跑 **sham** 模板（§5.4）；③ 对 **固定 K 题 unflagged** 跑 repair 与 sham（用于对照，§7.1.1）。**三类 repair 模板 + sham** 均为预注册文案，见 §5。
- **Tag → 模板**：默认映射 + `overrides.csv`；sham **不依赖** diagnosis tags。
- **报告**：分 **flagged / unflagged** 汇总 Δmetric、模板与 tag 分布、失败 case。

### 2.2 Out of Scope（本阶段不做）

- 开放式「让模型随便改写 prompt」的 repair。
- 用人类分布或正确答案提示模型。
- 全自动 adjudication 替代 `allow_unmapped: false` 下的人工 alias 维护（最多生成 **待复核队列**，不自动写进生产 alias）。
- 多模型联合诊断（单一 diagnosis 模型即可，与主实验模型可分离）。

---

## 3. Flagged Items 定义

### 3.1 默认规则（可配置）

在 `track_b.yaml` 或 CLI 参数中定义，建议 **全部基于轨道 A 已算出的 `item_metrics.csv`**（避免新口径）：

| 规则 ID | 条件（示例） | 说明 |
|---------|----------------|------|
| `F1` | `metric_family == cross_lingual` 且 `round_index == 1` 且 `top1_match == 0` | 与当前 `round2_candidates` 一致 |
| `F2` | 同上且 `jsd >= τ_xling`（如 0.25，可配置） | 减少「仅 tie-break 不同」的噪声 |
| `F3` | `metric_family == human_alignment` 且 `prompt_language == en` 且 `jsd >= τ_human` | 人类不对齐也 flag（**不**用于触发泄露，仅进入诊断/修复实验集） |

**默认建议**：MVP 仅用 **F1** 或 **F1 ∧ F2**，避免 flag 过多导致 API 成本爆炸。
  
注：在当前指标定义下，`focal_flip == 1` 与 cross-lingual `top1_match == 0` 等价，不单列为独立规则 ID。

### 3.2 成本上限与确定性截断（新增）

- 配置 `max_flagged_items = N`（必填，写入 manifest）。**报告/复现建议默认 `N = 8`**（可在 `track_b.yaml` 注明；实际以 manifest 为准）。
- 当命中数 `> N` 时，按以下**确定性**规则截断：  
  1) `jsd` 降序；  
  2) 若并列，按 `item_id` 字典序；  
  3) 取前 `N`。  
- 可选分层模式（`stratified_by_panel`）也必须是确定性的（固定层顺序 + 固定层内排序）。

### 3.3 输出制品

- `artifacts/track_b/<baseline_run_id>/flagged_items.json`  
  字段示例：`item_id`, `item_number`, `rules_fired`, `metrics_snapshot`（仅 EN/ZH LLM 侧指标，**无 human 列**）。

---

## 4. 固定 Taxonomy（诊断标签）

### 4.1 标签集合（封闭世界）

与 `update.pdf` 对齐，**只允许**以下标签（可多选，建议上限 3 个/条）：

| Tag ID | 名称 | 含义（用于写作与统计） |
|--------|------|-------------------------|
| `T_TRANS` | translation_asymmetry | EN/ZH 指令或类别名在语义强度、指称范围上不对称 |
| `T_CULT` | cultural_anchor_shift | 文化默认锚点导致焦点候选集合偏移（诊断层假设，非地面真值） |
| `T_LEAK` | output_language_leakage | 模型输出语言或格式违背约束，导致可比性下降 |
| `T_LEX` | lexical_granularity_mismatch | 粗细粒度不一致（专有名词 vs 类名） |
| `T_FRAG` | answer_space_fragmentation | 同义表达碎裂，归一化前分布已散 |
| `T_LITERAL` | over_literal_interpretation | 过度字面理解类别，协调目标未激活 |
| `T_SALIENCE` | prompt_salience_imbalance | 某一语言下 salient cue 不同 |
| `T_UNK` | insufficient_evidence | 证据不足，不强行归因 |

### 4.2 标注方式

**推荐：LLM + JSON schema + 校验器**

- **输入允许**：`item_text_en`, `item_text_zh`, `answer_language`, `prompt_language` 的 **题干与 system 指令模板**（与 A 轨一致）、**LLM 自身**在 EN/ZH 下的 **top-k 答案及近似频率**（仅模型输出统计，**非**人类分布）。
- **输入禁止**：`human_distributions.csv` 任一行、`canonical_answer` 人类先验排序、论文中人类众数名称。
- **输出 JSON schema**（示例）：

```json
{
  "item_id": "study2_item_03",
  "tags": ["T_TRANS", "T_SALIENCE"],
  "evidence": "Short bilingual comparison in <= 80 words.",
  "confidence": "medium"
}
```

- **校验**：`tags` 必须 ⊆ 上表；非法则回退 `T_UNK`。

### 4.3 输出制品

- `artifacts/track_b/<baseline_run_id>/diagnosis/<item_id>.json`

### 4.4 可选：纯规则 baseline

不调用 LLM 时：所有 flagged 标为 `T_UNK`，repair 走默认模板（如 `coordination_reminder`），用于 dry-run。

---

## 5. 模板化 Repair（三类 repair + sham）

### 5.1 模板 ID 与作用

| 模板 ID | 名称 | 作用 | 默认适用 tags |
|---------|------|------|----------------|
| `R_SEM` | semantic_parity | 对 EN/ZH **成对**增补对称短说明，收紧语义对等（不引入新任务信息） | `T_TRANS`, `T_SALIENCE` |
| `R_FMT` | format_repair | 强化 **单行、短答、名词短语、禁止解释** | `T_LEAK`, `T_LEX`, `T_FRAG` |
| `R_COORD` | coordination_reminder | 轻量重复协调目标（与 A 轨 round2 类似但 **文案固定为模板**） | `T_LITERAL`, `T_UNK`, 默认 fallback |
| `R_SHAM` | sham_control | **无信息对照**：仅作标点/换行/等价衔接词等改写，**不改变**协调目标、类别信息、输出语言约束的强度；用于估计「多采一轮 + 模板壳」相对 baseline 的偏移（§7） | （按 item 固定施加，**不**由 tag 映射） |

### 5.2 模板内容原则

- **变量占位符**仅限：`{item_text_en}`, `{item_text_zh}`, `{answer_language}`, `{context_en}`, `{context_zh}`（与 `build_prompt_messages` 一致），**禁止** `{human_hint}` 等。
- 每个模板对应 **明确 system + user 片段**，存于 `src/coordbench/track_b/repair_templates.yaml`（或 `.toml`）。
- **Tag → 默认模板**：`track_b/tag_to_repair.yaml`（**仅** `R_SEM` / `R_FMT` / `R_COORD`）；允许 `artifacts/track_b/overrides.csv` 人工改 `item_id → repair_template_id`。`R_SHAM` **单独列**在采样清单中，不参与 tag 映射。

### 5.3 与现有 round2 的关系

- **方案 B（MVP 推荐）**：单独 `track_b_run` 目录，对 **flagged ∪ unflagged 对照** 分别调度 **repair** 与 **sham** 采样（或两个子 run），manifest 指向同一 `prepared_snapshot_id`；分析脚本与 A 轨 baseline **合并** CSV。**实现更轻，回归面更小**。
- **方案 A（后续重构）**：新增 `round_index == 3` 或字段 `track_b_arm: baseline | repair`，在 `build_prompt_messages` 分支加载 repair 模板；**轨道 A 的 round1/2 行为不变**。

MVP 先落地方案 B；稳定后再评估是否迁移到方案 A。snapshot 错配通过 `prepared_snapshot_id` + `frozen_track_a_commit` 双重绑定控制。

### 5.4 Sham 模板（必填规格）

- **目的**：与 repair 使用 **同一套占位符与同一 `round1_samples`**，仅 user/system 文案在 **预注册** 下做无语义增量改写（例如多一行「请作答。」或与 baseline 等长的 filler，**不得**加强协调、格式或翻译对称性）。
- **审计**：sham 与 repair 走 **同一 allowlist**；禁止借 sham 注入人类或答案提示。
- **实现**：`repair_templates.yaml` 中为 `R_SHAM` 存独立片段；`audit-prompts` 对 sham run 同样执行 §6.3。

---

## 6. 不泄露人类分布：协议与审计

### 6.1 黑名单（不得出现在 Diagnosis / Repair 的 prompt 中）

- `human_distributions.csv`、`participant_responses.csv` 聚合结果  
- 任一 `human_top1`、`probability`、`consensus_bucket` 的 **数值或答案字符串**（若该字符串仅来自人类标注而非题干）  
- 「大多数人类会答…」「常见答案是…」等暗示  
- 论文附录中的 **人类众数表**

### 6.2 白名单（允许）

- 题干 `item_text_en` / `item_text_zh`（来自 panel，非答案统计）  
- `answer_language`、target group 描述  
- **模型自身**在 EN / ZH prompt 下采样的 top-k 与计数（仅用于诊断「模型是否碎裂」）

### 6.3 审计步骤（每次提交前）

1. `coordbench track-b audit-prompts --run ...`：先做**字段级 allowlist 审计**（Diagnosis/Repair payload 仅允许预注册字段）。  
2. 再做关键字与正则黑名单扫描（`probability`, `human`, `distribution`, 人类答案列表路径等）。  
3. 人工抽查 10% flagged items 的完整 request payload。  
4. 在 `run_manifest.json` 写入 `track_b_no_human_leak_attestation: true` 及审计命令哈希（可选）。

---

## 7. 受控前后对照（实验设计）

### 7.1 因子

| 因子 | 水平 |
|------|------|
| Arm | `baseline`（**锁定为 A 轨 round1-only 快照**） / `repair`（同配置 + repair 模板额外采样） / `sham`（同配置 + 无信息改写） |
| Item | `flagged` 子集 + 固定 K 个 `unflagged` 对照项（由 §7.1.1 确定性选出） |
| Provider / Model / decoding | **与 baseline 完全相同** |

### 7.1.1 Unflagged 对照题（确定性选取）

配置 `unflagged_control_count = K`（必填，写入 manifest；**建议默认 `K = 3`**，且 `K` 小于未 flag 题数）。

在 **同一 `panel_id`、同一 `item_metrics.csv`（round1）** 上：

1. 候选集：`metric_family == cross_lingual` 且 `round_index == 1` 且 **`top1_match == 1`** 且 **未**进入截断后的 `flagged` 列表。  
2. 在候选集中按 **`jsd` 升序**（最「稳」的题优先作对照）；`jsd` 并列则按 **`item_id` 字典序**。  
3. 取前 **`K`** 题写入 `unflagged_controls.json`（字段含 `item_id`, `jsd_at_select`, `rule` 摘要）。

若候选不足 `K`，manifest 记 `unflagged_control_warning`，并取 **全部**候选（仍确定性排序）。

### 7.2 采样预算

- 建议：`repair` 与 `sham` 侧 **与 round1 同 `round1_samples`**（或减半做 pilot），在 `track_b.yaml` 配置。  
- 随机种子：`baseline_seed + item_hash + arm` 固定规则，写入 manifest。

### 7.3 指标对比

- 每个 item（flagged + unflagged 对照）：  
  - cross-lingual：`jsd`, `tvd`, `top1_match`, `flip_rate`  
  - human_alignment（EN / ZH 分列）：`jsd`, `top1_match`  
- **分层报告**（避免混读）：  
  - **Primary（论文主表）**：仅 **flagged** 子集的 `mean(ΔJSD_repair−baseline)`、`mean(ΔJSD_sham−baseline)`，及 pre-spec 的 95% CI（§7.4）。  
  - **Secondary**：**unflagged** 上同口径 Δ（预期接近 0；若 sham 在 unflagged 上仍大，提示归一化或采样噪声，需在 limitation 讨论）。  
- **探索性聚合**：flagged 内按 `repair_template_id`（非 sham）、按 `tag` 分组的平均 Δ。

### 7.4 统计与写作

- 复用现有 bootstrap（item 级 JSD 等）；预先声明 primary endpoint：`flagged` 子集上的 `mean(ΔJSD_repair−baseline)`，并报告 95% CI；**建议并列** `mean(ΔJSD_sham−baseline)`（同 flagged 子集）以分离「重采样/壳」效应。  
- Track B 明确为探索性分析：multiple testing 未校正，在结论中避免确证性措辞。  
- 报告 **失败例**：repair 后 JSD 上升或 top-1 仍不一致的 item，附 diagnosis 引用。

---

## 8. 代码与 CLI 改动清单（建议顺序）

1. **`coordbench.models` / config**  
   - 新增可选块 `track_b:`：`enabled`, `flag_rules`, `tau_xling`, `tau_human`, `max_flagged_items`, `unflagged_control_count`, `diagnosis_model`（可复用某 provider）, `repair_template_dir`, `repair_samples`, `seed_offset`。  
   - **Baseline 口径**：**不写可调开关**；代码常量 `TRACK_B_BASELINE = track_a_round1_only`（与 §7.1 一致），写入 manifest 备查。

2. **`coordbench/track_b/` 包**（新）  
   - `flags.py`：读 `item_metrics.csv` → `flagged_items.json`  
   - `diagnosis.py`：渲染 diagnosis prompt，调 provider，写 JSON  
   - `repair_templates.yaml` + `render_repair_prompt(...)`  
   - `map_tag_to_template(...)`  
   - `audit.py`：字段级 allowlist + 关键词黑名单扫描  

3. **`prompts.py`**  
   - `build_prompt_messages(..., track_b_phase: Literal["none","repair"] | None)` 或 `round_index` 扩展 + `repair_template_id`。

4. **`runner.py` / `cli.py`**  
   - 子命令：`coordbench track-b flag`, `diagnose`, `sample-repair`, `analyze-compare`, `report`, `audit-prompts`  
   - 或单一 `coordbench track-b run --baseline-run-id ...` 顺序执行。

5. **`analysis.py`（小改）**  
   - 支持按 `track_b_arm` 或 `round_index` 分组输出；或合并两 CSV 的对比脚本 `track_b/compare_runs.py`。

6. **测试**  
   - `tests/test_track_b_audit.py`：含一段 **伪造 human 表** 确保绝不注入 prompt。  
   - `tests/test_track_b_templates.py`：模板渲染无未定义占位符。

7. **文档**  
   - 更新 `README.md` 一节；统一 canonical 风险文档路径为 `docs/risks/RAW_DATA_AND_RISKS.md`。  
   - 若保留 `docs/RAW_DATA_AND_RISKS.md`，仅作为 redirect stub（单行指向 canonical 路径）。

---

## 9. 制品目录结构（建议）

```text
artifacts/track_b/<baseline_run_id>/
  flagged_items.json
  unflagged_controls.json
  diagnosis/
    <item_id>.json
  repair_manifest.yaml          # item_id -> template_id, seed, samples
  raw_repair_generations.jsonl  # 或并入主 run 带列 track_b_arm
  item_metrics_compare.csv      # baseline vs repair 并列
  track_b_report.md
  audit/
    prompt_hashes.txt
```

---

## 10. 里程碑与时间（参考）

| 阶段 | 交付 | 人天（估） |
|------|------|------------|
| M0 | 本 plan + flag 规则定稿 | 0.5 |
| M1 | `flag` + `flagged_items.json` + 测试 | 1 |
| M2 | 三类 repair + **sham** 模板 + 渲染 + audit 脚本 | 1–2 |
| M3 | `sample-repair` 接入 runner + manifest | 2 |
| M4 | diagnosis LLM + schema 校验 | 1–2 |
| M5 | 对比分析 + `track_b_report.md` | 1 |
| M6 | README + 与论文 Methods 对齐 | 0.5 |

**合计**：约 **6–10 人日**（单人全职连续块）。

---

## 11. 风险与缓解

| 风险 | 缓解 |
|------|------|
| Repair 仍无意泄露人类信息 | 模板固定 + 自动化 audit + 不用 RAG 检索人类表 |
| Flag 过多 / API 成本 | 默认 F1∧F2 + 每 run 上限 N 个 item |
| diagnosis 胡编标签 | 封闭 tag 集 + `T_UNK` + 写作中写「启发式归因」 |
| 与轨道 A 混淆 | manifest 字段 `frozen_track_a_commit` / `track_b_version` |
| 归一化扭曲 Δmetric | repair 前后 **同一 normalization 配置**；报告 unresolved 比例 |

---

## 12. 论文 Methods 可摘用的一句话（草案）

> After frozen Track-A evaluation, we flag items by pre-registered rules on model-only statistics. A lightweight diagnosis step assigns **closed-vocabulary failure tags** using prompts that **exclude human response distributions**. We then apply **three hand-authored repair templates** (semantic parity, format tightening, coordination reminder) and a **sham control template** that makes no substantive change to the task, alongside **deterministically sampled unflagged items**, resampling with **identical decoding and sample budgets** as Track-A round 1. We report **paired changes** in cross-lingual divergence and human alignment metrics, with the **primary endpoint** on flagged items and **secondary checks** on unflagged controls.

---

## 13. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-04-13 | v2.1：§2.1 与 §7 对齐（MVP 必含 sham + unflagged）；§5 增加 `R_SHAM` 与 §5.4；§7.1.1 unflagged 确定性选取；§7.3 分层报告；§3.2 默认 `N=8`；§8 去掉 `baseline_arm`、改为常量口径；§9 增加 `unflagged_controls.json`；Methods 句更新 |
| 2026-04-13 | v2：删 F4；加入确定性截断；baseline 锁定 round1-only；加入 sham + unflagged 对照；审计升级为 allowlist+blacklist；MVP 改为方案 B 优先；统一风险文档 canonical 路径 |
| 2026-04-12 | 初稿：轻量 B 范围、taxonomy、模板、协议、实现顺序与里程碑 |
