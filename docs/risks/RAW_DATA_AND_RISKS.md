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
- **默认 config（历史）** 曾开启 **`allow_unmapped: true`**：模型新说法可不进入人类词表仍参与统计。
- **后果**：LLM 经验分布的支撑可 **严格大于** 人类表支撑；与 Proposal / 论文叙述中「在人类 canonical 上度量 JSD、对齐」易不一致；未映射质量可能落在空串、保留原样或 fuzzy 边界 case，**系统性扭曲 RQ1（人类对齐）与部分 RQ2 解释**。
- **建议**：发表级跑法采用 **`allow_unmapped: false`**，并扩充 `default_aliases.csv` + `unresolved_queue` 人工规则；与 README 中 “publication-tight” 叙述对齐。
- **代码定位**：`src/coordbench/normalize.py` 中 `elif config.normalization.allow_unmapped:` 分支；默认 config 在 `configs/study2_british_en_zh.yaml` / `configs/universal_api_full.yaml` 设为 `true`。
- **2026-04-11 已修改**：默认值已调整为更保守口径。
  - `src/coordbench/config.py` 中 `allow_unmapped` 缺省从 `true` 改为 `false`。
  - `configs/study2_british_en_zh.yaml` 与 `configs/universal_api_full.yaml` 的 `allow_unmapped` 已从 `true` 改为 `false`。
- **实测证据（2026-04-10 核查）**：`results/previous/runs/runs-gemini-2.5-flash/20260401T075525Z/normalized_outputs.csv` 出现 `unmapped=49/1000`；按语言 EN `10/500`，ZH `39/500`（ZH 侧更高）。

### 4.2 【高】`default_aliases.csv` 与 **Raw 表面形式** 是否同步

- 人类 raw 中高频拼写、缩写、标点变体进入 `answer_key` / canonical；若别名表未覆盖模型与人类常见写法，会大量依赖 **fuzzy** 或 **unmapped**。
- **风险**：非「单点 bug」，而是 **数据资产与某一 `snapshot_id` 下的人类分布不同步** 时的 **系统性度量偏误**。
- **2026-04-12 已修改**：归一化阶段增加“人类面形式自动同步 + 覆盖审计”。
  - `src/coordbench/normalize.py` 在读取静态 alias 后，会从 `participant_responses.csv` 自动补齐可映射的面形式（`response_original` / `response_clean` / canonical）。
  - 每次 `normalize` 产出 `alias_coverage_report.csv`（按 `(panel_id,item_id)` 给出 human key 覆盖率）。
  - `unresolved_queue.csv` 现增加 `closest_human_answer_key` / `closest_human_canonical` / `closest_human_score`，便于人工扩充 alias。
  - 这样 alias 不再只依赖手工静态表，降低 snapshot 变更带来的系统性失配。
- **2026-04-12（gpt-5.4 recheck4）并入记录**：基于 `unresolved_queue` 建议项人工并入别名后已复跑。
  - `data/aliases/default_aliases.csv` 新增：`Pound sterling/Pound Sterling -> pound`、`Harry Potter and the Philosopher's Stone -> harrypotter`（含直/弯引号变体）、`Elvis Presley -> elvis`、`Queen Elizabeth II -> queenelizabeth`。
  - 目标 run `20260412T043325Z` 的 unresolved 从 **136 降至 30**，剩余均为 `study2_item_04` 的 `house/church`（低相似度，需人工语义判定，不建议自动并入）。

### 4.3 【中高】`prepare.py` 对 **CSV 布局硬编码**

- Study2：`rows[2:]`、字段 `country_cat`、`item_1_uk`…`item_15_uk` 等；Study1/Study3 类似。
- OSF 若更新导出 **无版本锁**，易出现 **难察觉** 的数据错误。
- **建议**：对关键制品做 **回归测试**（已有 tests/fixtures方向）+重要论文冻结 `source_manifest` / 校验行数与列存在性。
- **代码定位**：`src/coordbench/dataset/prepare.py` 中 `_study2_rows()` / `_study3_rows()` 的 `rows[2:]`、列名硬编码与 item 列列表。
- **2026-04-12 已修改**：`prepare.py` 增加了 schema/布局防漂移保护。
  - 新增 `Study1/2/3` 必要列校验（缺列直接抛错，不再静默错列）。
  - Study2/Study3 从固定 `rows[2:]` 改为基于 `ResponseId` 的数据起始行检测（仍兼容旧快照，但对导出格式变动更稳健）。
  - 当 CSV 缺少 prompt/data 关键行时直接报错，避免继续生成污染制品。
- **当前状态（20260324T070530Z）**：`Study1/2/3.csv` 的关键列（`condition `、`country_cat`、`ResponseId`、`Country`、`op1..op30`、`item_*_uk/sa/glo`）均存在；当前 snapshot 下解析可对齐，但升级 raw 后仍需复核。

### 4.4 【中】英文题干解析链路：`Table_of_Alignment_Items.docx` + 启发式 `_extract_prompt_from_raw`

- 题干将 CSV 首行与 Word 表对齐；含 `PROMPT_KEY_OVERRIDES` 与模糊匹配。
- **风险**：边界题上 `item_text_en` 若与论文意图不一致，会 **同时污染** 人类聚合（若列对齐错）与 **LLM 提示**。
- **2026-04-12 已修改**：题干提取链路增加了可审计性。
  - `src/coordbench/dataset/prepare.py` 新增 `_extract_prompt_from_raw_with_reason`，对每个题干保留提取方法标签（如 `table_match` / `item_number_fallback` / `regex_fallback`）。
  - `prepare_human_panels` 新增输出 `prompt_extraction_audit.csv`，可按 `source_file/source_column/item_id` 复核题干映射。
  - 若出现 `regex_fallback` / `generic_item_fallback`，prepare 阶段会发出 warning，避免静默污染进入后续评估。

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
- **2026-04-12 已修改**：支持 config 级显式题目子集。
  - `src/coordbench/models.py` / `src/coordbench/config.py` 新增 `sampling.item_ids`。
  - `src/coordbench/runner.py` 在 round1 默认读取 `sampling.item_ids` 作为采样子集（round2 仍以候选题驱动）。
  - `src/coordbench/cli.py` 新增 `run-sampling --item-ids a,b,c`，可临时覆盖配置子集。
  - 这样可以直接按 Proposal 口径固定 15–20 题 manifest，而不是被动跑整 panel。

### 5.3 【中】RQ3 第二轮「失败」定义

- Proposal：**Type1** EN/ZH top-1 不一致；**Type2（可选）** LLM top-1 ≠ Human top-1。
- 代码（当前）：`round2_candidates` 已按 `sampling.round2_trigger` 分支生成，可用 **Type1 / Type2 / either** 触发。
- **写作**：正文需明确你们实际采用的触发口径（Type1 或 Type2 或 either），并在 Methods 中与 config 一致。
- **代码定位（当前）**：`src/coordbench/config.py` 读取 `sampling.round2_trigger`；`src/coordbench/analysis.py` 在 `round2_candidates` 生成处按该值分支，不再硬编码单一触发条件。
- **应修改位置**：`src/coordbench/analysis.py` 的 `analyze_run()` 内 `round2_candidates` 生成块（写入 `round2_candidates.csv` 前），应按 `round2_trigger` 分支支持 Type1 / Type2 / either。
- **2026-04-11 已修改**：`src/coordbench/analysis.py` 已按 `sampling.round2_trigger` 分支生成 `round2_candidates.csv`，支持：
  - `cross_lingual_top1_mismatch`（Type1）
  - `human_top1_mismatch`（Type2）
  - `either_top1_mismatch`（Type1 ∪ Type2）
  同时新增测试 `tests/test_normalize_analysis.py::test_round2_candidates_respect_configured_trigger` 覆盖上述分支。
- **实测证据（2026-04-10 核查）**：`results/previous/runs/runs-gemini-2.5-flash/20260401T075525Z/round2_candidates.csv` 为 5 项，触发来源与现有硬编码一致（Type1）。

### 5.4 【低–中】指标列语义

- `human_alignment` 族中 **`flip_rate` 恒为 0**；跨语 flip 只在 `cross_lingual` 行有意义。
- **写作**：避免把「相对人类的 top-1」误称为 flip；用 **`top1_match`** 等对人类列。
- **2026-04-12 已修改**：`human_alignment` 行的 `flip_rate` 改为不适用（空值），并且 aggregate bootstrap 不再对 `human_alignment` 计算 flip 区间；flip 只保留在 `cross_lingual` 语义范围。

### 5.5 【低–中】分层分析作图范围

- Proposal：bucket 上可对 top-1、JSD、flip 作对比。
- 代码：consensus 图主要体现 **跨语 JSD**；其余可从 `item_metrics.csv` 自算，或与正文统一为「主图仅 JSD，余附录」。
- **2026-04-12 已修改**：bucket 作图扩展为三指标并行输出。
  - `src/coordbench/plots.py` 现在按 `consensus_bucket` 同时汇总 `mean_jsd` / `mean_top1_match` / `mean_flip_rate`。
  - 新增 `plots/consensus_bucket_metrics.{png,pdf}`，可直接对应 Proposal 的 bucket 对比叙述。

### 5.6 【中】实验设计：多 Provider 同 config

- 默认 yaml 可 **多厂商并行**；论文若强调 **单模型、固定解码**，应 **单开 provider** 或分 run，并在文中固定 temperature、max tokens、采样数与种子。
- **2026-04-12 已修改**：增加单 run provider 数量保护。
  - `src/coordbench/config.py` / `src/coordbench/models.py` 新增 `sampling.max_enabled_providers`（默认 `1`）。
  - `src/coordbench/runner.py` 在采样前校验启用 provider 数，超限则直接报错，避免同一 run 混模型口径。
  - `configs/study2_british_en_zh.yaml` 已改为默认单 provider（openai）并显式 `max_enabled_providers: 1`。

### 5.7 【低】Bootstrap 覆盖

Item 层 bootstrap 代码对 **JSD** 有较完整区间；若正文承诺 **TVD / Spearman 题级区间**，需核对是否实现或改口径。
- **2026-04-12 已修改**：item-level bootstrap 已扩展到 `JSD + TVD + Spearman`（可计算时）。
  - `src/coordbench/analysis.py::_item_level_bootstrap()` 现在同时为 cross-lingual 与 human-alignment 产出 `metric in {jsd,tvd,spearman}` 的区间行。
  - `spearman` 在抽样分布支撑不足时自动跳过，避免写入伪区间。

### 5.8 【中】Cross-lingual 与 Human-alignment 的门控耦合

- Proposal 中 `A. Cross-Lingual Consistency` 是 **LLM 内部一致性**，不应被人类映射成功率直接门控。
- 历史实现会先过滤 `canonical_answer == ""` 再计算两类指标，导致 cross-lingual 也受 human/alias 映射质量影响。
- **2026-04-12 已修改为双轨**：
  - `src/coordbench/normalize.py` 新增 `coord_answer` 字段：仅基于有效模型输出的清洗答案，用于 cross-lingual 轨道。
  - `src/coordbench/analysis.py` 分离两套 completeness：
    - `coord_cell_completeness.csv`：用于 `cross_lingual`（基于 `coord_answer`）。
    - `cell_completeness.csv`：用于 `human_alignment`（基于 `canonical_answer`）。
  - `item_metrics.csv` 仍统一输出两类指标，但其进入条件分别来自对应轨道，不再共享同一门控。
  - `run_manifest.json` 新增：
    - `complete_cell_count_cross_lingual` / `incomplete_cell_count_cross_lingual`
    - `complete_cell_count_human_alignment` / `incomplete_cell_count_human_alignment`
- **2026-04-12 进一步更新（同义词同步）**：
  - cross-lingual 主键从 `coord_answer` 进一步收敛为 `coord_answer_key`（大小写/空格/标点统一）。
  - `normalize.py` 在 alias 命中时，将 `coord_answer_key` 同步到 alias 对应 canonical key（例如 `pound sterling -> pound`）。
  - `coord_answer_key` 规则新增轻量语义归并：`mount/mt/mountain` 前缀可省略；在人物题（如 `study2_item_02/03/08/12`）中，全名与姓氏按姓聚合。
  - 该同步仅用于 coordination 轨道的“同义词对齐”，不引入 `human_key/fuzzy` 的门控语义，仍保持 Proposal 中 LLM-internal consistency 的独立性。

---

## 6. 建议的检查清单（小组内部）

1. **快照**：`prepared_snapshot_id` 与论文预注册/附录是否一致；是否冻结 OSF 版本。  
2. **题干**：`panel_items.csv` 中 **`item_text_zh` 是否均为真实中文**（无 fallback 英文）。  
3. **归一化**：终稿是否 `allow_unmapped: false` + alias 审计 + unresolved 处理完毕。  
4. **RQ1/RQ2**：指标是否按 **prompt 语言** 与 **跨语** 分行报告，不混表。  
5. **RQ3**：正文触发条件与代码 **Type1/Type2** 一致。  
6. **Prepare**：Study1/2/3 CSV 与当前 OSF 文件 **列名、行偏移** 是否仍匹配（升级 raw 后必查）。
7. **路径口径**：Methods 明确使用的 run 根目录与证据文件（默认 `outputs.run_root=../artifacts/runs`；历史结果在 `results/previous/...`，近期 50-sample 归档在 `results/runs_s50/...`）。
