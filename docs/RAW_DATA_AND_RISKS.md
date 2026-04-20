# Raw Data 与框架级问题 / 风险说明

本文档说明 CoordBench 所依赖的 **OSF 原始数据**如何进入流水线，并系统列出相对 **Proposal 口径**与 **当前 code/config** 的 **大框架级问题与风险**，供复现、写论文 Methods/Limitations 与排错使用。

---

## 1. 原始数据来源与获取

### 1.1 文献与 OSF

- **数据论文**：Perez-Zapata et al., *Three International Studies on Pure Coordination Games*（JEP: General；项目 Proposal 中引用）。
- **OSF 项目**：公开材料与 Qualtrics 导出等，默认由 CLI `coordbench fetch-source-data` 拉取（见 `README.md` 中 OSF 链接）。
- 拉取结果落在版本化 **source snapshot** 目录下，并由 `source_manifest.json` 记录 `snapshot_id`。

### 1.2 原始侧关键文件（典型布局）

在某一 **source snapshot** 内，与重建人类 panel 直接相关的包括（路径以代码为准，见 `coordbench.dataset.prepare`）：

| 类别 | 典型路径 | 作用 |
|------|-----------|------|
| Study1 导出 | `datasets/Study1.csv` | 英国/全球被试；最多 30 题；首行为题干将本列映射到 alignment表 |
| Study2 导出 | `datasets/Study2.csv` | 英国/南非；within/between；**15 题**子集列（如 `item_*_uk` / `item_*_sa`）；数据行跳过表头后固定偏移 |
| Study3 导出 | `datasets/Study3.csv` | 智利/南非等；类似结构，列名与 panel 定义在代码中硬编码 |
| Alignment 材料 | `materials/Table_of_Alignment_Items.docx` | 题号与英文协调提示（“Name a …”）的权威对齐表；解析后得到 `item_table` |

**注意**：具体列名、跳过行数、国家/条件字段名均由 `prepare.py` **写死**。若 OSF 更换 CSV 导出格式而未同步改代码，可能导致 **静默错列、少答、空 panel**。

---

## 2. 从 Raw 到「可跑 benchmark」的制品

### 2.1 `prepare_human_panels` 产出（`data/prepared/<snapshot_id>/`）

- **`participant_responses.csv`**：被试 × 题 × 原始/清洗答案、`answer_key`、英文题干 `item_text_en`、**中文题干 `item_text_zh`**（见下节）、`panel_id`、`item_id` 等。
- **`human_distributions.csv`**：在 `(panel_id, item_id, answer_key)` 上聚合为 **canonical 答案**与 **经验概率**（人类分布）。
- **`panel_items.csv`**：每题在各区 panel 的元数据（含 `item_text_en` / `item_text_zh` 等）。
- 另有 `panel_summary.csv`、`dataset_inventory.json`、`benchmark_manifest.json`、`selection_report.md` 等（由 profile等步骤维护/推荐默认 panel）。

### 2.2 默认 benchmark panel

仓库与 `profile` 逻辑将 **`study2_british_within`** 作为官方默认：**约 15 题、100 名被试、人类答案为英文**，与「固定英文作答」的 LLM 设定一致（见 `dataset/profile.py` 与 README）。

### 2.3 中文题干 **不在** OSF Raw 中

- `item_text_zh` 由 `coordbench.prompts.translate_item(item_text_en)` 根据仓库内 **硬编码字典**生成，**不是** Qualtrics 或论文补充材料中的字段。
- **风险**：任一英文题干若未在字典中覆盖，会 **fallback 为英文原文**，此时「中文提示」与 Proposal 中「中英同一协调目标」在 **题级**可能不成立；需在 `panel_items.csv` 上人工核对。

---

## 3. Config 与路径（相对 raw / 制品）

- **YAML位置**：如 `configs/study2_british_en_zh.yaml`。
- **`normalization.alias_path`**：通常为相对 config 目录的 `../data/aliases/default_aliases.csv`，解析后为 **仓库内别名表**，用于将 **模型输出字符串** 映射到 **人类 canonical**。
- **`sampling.panel_id`**：必须与当前使用的 prepared快照中 panel 一致（如 `study2_british_within`）。
- **`allow_unmapped`**：是否允许无法映射的模型答案仍进入下游（见第 4 节）。
- **Run 目录** `artifacts/runs/<run_id>/` 通过 `run_manifest.json` 绑定 **`prepared_snapshot_id`**；换快照后应用新 run，避免与旧人类表混用。

---

## 4. 相对当前 Raw 与人类表：Code / Config 的最大风险

### 4.1 【高】`allow_unmapped: true` 与人类离散分布的 **支撑集不一致**

- **人类侧**（由 raw 聚合）：每个 `(panel_id, item_id)` 上分布支撑在 **有限个 canonical 答案**上。
- **默认 config** 常开启 **`allow_unmapped: true`**：模型新说法可不进入人类词表仍参与统计。
- **后果**：LLM 经验分布的支撑可 **严格大于** 人类表支撑；与 Proposal / 论文叙述中「在人类 canonical 上度量 JSD、对齐」易不一致；未映射质量可能落在空串、保留原样或 fuzzy 边界 case，**系统性扭曲 RQ1（人类对齐）与部分 RQ2 解释**。
- **建议**：发表级跑法采用 **`allow_unmapped: false`**，并扩充 `default_aliases.csv` + `unresolved_queue` 人工规则；与 README 中 “publication-tight” 叙述对齐。

### 4.2 【高】`default_aliases.csv` 与 **Raw 表面形式** 是否同步

- 人类 raw 中高频拼写、缩写、标点变体进入 `answer_key` / canonical；若别名表未覆盖模型与人类常见写法，会大量依赖 **fuzzy** 或 **unmapped**。
- **风险**：非「单点 bug」，而是 **数据资产与某一 `snapshot_id` 下的人类分布不同步** 时的 **系统性度量偏误**。

### 4.3 【中高】`prepare.py` 对 **CSV 布局硬编码**

- Study2：`rows[2:]`、字段 `country_cat`、`item_1_uk`…`item_15_uk` 等；Study1/Study3 类似。
- OSF 若更新导出 **无版本锁**，易出现 **难察觉** 的数据错误。
- **建议**：对关键制品做 **回归测试**（已有 tests/fixtures方向）+重要论文冻结 `source_manifest` / 校验行数与列存在性。

### 4.4 【中】英文题干解析链路：`Table_of_Alignment_Items.docx` + 启发式 `_extract_prompt_from_raw`

- 题干将 CSV 首行与 Word 表对齐；含 `PROMPT_KEY_OVERRIDES` 与模糊匹配。
- **风险**：边界题上 `item_text_en` 若与论文意图不一致，会 **同时污染** 人类聚合（若列对齐错）与 **LLM 提示**。

---

## 5. 相对 Proposal：框架级对齐与缺口

以下对照 **COMP3520 Proposal** 中的目标与指标叙述（RQ1–RQ3、第二轮、分层等）。

### 5.1 已较好覆盖的叙事

- 人类分布 + 可复现流水线（fetch → prepare → sample → normalize → analyze → plot）。
- EN/ZH 提示 + **作答语言固定**（config 中 `prompt_languages` + `answer_language`）。
- 跨语：**JSD / TVD / top-1 一致 / flip**；人类对齐：**JSD、top-1、Spearman（可选）**。
- **Bootstrap**（汇总与题级 JSD）。
- **共识分层** `consensus_bucket`（按人类 top1 概率三分位）；图中有跨语 JSD by bucket 等。
- **第二轮**：prompt 层保持协调目标、不泄露人类分布；`run-all` 可对候选题再采样。

### 5.2 【中】题目子集与「15–20 题、共识多样」

- 实现上默认跑满 **整 panel**（如 `study2_british_within` 约 15 题），而非 Proposal 字面意义的「再抽 15–20 题子集」的独立 manifest。
- **写作**：需在 Methods 说明「采用默认 panel 即全题」或 **显式列出 `item_id`** 子集 config。

### 5.3 【中】RQ3 第二轮「失败」定义

- Proposal：**Type1** EN/ZH top-1 不一致；**Type2（可选）** LLM top-1 ≠ Human top-1。
- 代码：`round2_candidates` 当前由 **cross_lingual + round1 + top1 不匹配** 驱动；`round2_trigger` **未**实现「仅因人类不对齐也进第二轮」的分支。
- **写作**：若正文写 Type2，须 **改分析侧候选生成** 或 **改成仅报告 Type1**。

### 5.4 【低–中】指标列语义

- `human_alignment` 族中 **`flip_rate` 恒为 0**；跨语 flip 只在 `cross_lingual` 行有意义。
- **写作**：避免把「相对人类的 top-1」误称为 flip；用 **`top1_match`** 等对人类列。

### 5.5 【低–中】分层分析作图范围

- Proposal：bucket 上可对 top-1、JSD、flip 作对比。
- 代码：consensus 图主要体现 **跨语 JSD**；其余可从 `item_metrics.csv` 自算，或与正文统一为「主图仅 JSD，余附录」。

### 5.6 【中】实验设计：多 Provider 同 config

- 默认 yaml 可 **多厂商并行**；论文若强调 **单模型、固定解码**，应 **单开 provider** 或分 run，并在文中固定 temperature、max tokens、采样数与种子。

### 5.7 【低】Bootstrap 覆盖

Item 层 bootstrap 代码对 **JSD** 有较完整区间；若正文承诺 **TVD / Spearman 题级区间**，需核对是否实现或改口径。

---

## 6. 建议的检查清单（小组内部）

1. **快照**：`prepared_snapshot_id` 与论文预注册/附录是否一致；是否冻结 OSF 版本。  
2. **题干**：`panel_items.csv` 中 **`item_text_zh` 是否均为真实中文**（无 fallback 英文）。  
3. **归一化**：终稿是否 `allow_unmapped: false` + alias 审计 + unresolved 处理完毕。  
4. **RQ1/RQ2**：指标是否按 **prompt 语言** 与 **跨语** 分行报告，不混表。  
5. **RQ3**：正文触发条件与代码 **Type1/Type2** 一致。  
6. **Prepare**：Study1/2/3 CSV 与当前 OSF 文件 **列名、行偏移** 是否仍匹配（升级 raw 后必查）。

---

## 7. 文档维护

- 代码路径以 `src/coordbench/` 为准；若重构目录或默认 config，请同步更新本节路径与行为描述。
- 本文档 **不**包含任何 API Key 或私有数据路径；环境变量与 `.env` 见 `README.md` 与 `.env.example`。
