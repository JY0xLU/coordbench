# Track B Agent — Code + Results Summary

## What this agent implemented (in-repo “开箱即用” Track B)

This repo originally had a Track B scaffold under `Agent/`. Integrated Track B now lives in **`Agent/src/track_b_agent/integrated/`**; the **`coordbench track-b run`** command delegates to it when the Agent package is installed (`pip install -e Agent`). Core `coordbench` still supplies sampling, normalize, analyze, and providers.

### New core capability: `coordbench track-b run`

Adds a ready-to-run pipeline that, given a **baseline run directory** (must already have `item_metrics.csv`):

- **Flag** failing items from baseline round 1 cross-lingual metrics
- **Diagnose** each flagged item using the configured LLM (JSON tag output)
- **Sample** two arms for the selected items:
  - **repair arm** (default `round_index=3`)
  - **sham arm** (default `round_index=4`)
- **Normalize** + **Analyze**
- Emit `track_b_report.md` with per-item and flagged-mean deltas vs baseline round 1

CLI usage (baseline path recommended to avoid `run_root` confusion):

```bash
coordbench track-b run \
  --config configs/study2_deepseek_s50.yaml \
  --baseline-run /ABS/PATH/TO/baseline_run_dir \
  --provider deepseek
```

Optional switches:
- `--stub-diagnose`: skip diagnosis calls and use `T_UNK → R_COORD` for all flagged items
- `--track-b-config`: override Track B flag rule YAML
- `--repair-round`, `--sham-round`: override the default round indices

### Agent package layout (`Agent/src/track_b_agent/`)

- **`integrated/`** — end-to-end pipeline: `pipeline.py`, `diagnosis.py`, `sampling.py`, `report.py`, `templates.py`, `progress.py`
- **`flags.py`** — flag + unflagged control selection; writes `flagged_items.json`, `unflagged_controls.json`, `track_b_manifest.json`
- **YAML** — `Agent/prompts/repair_templates.yaml`, `Agent/prompts/tag_to_repair.yaml`, `Agent/config/track_b.example.yaml`

The former `src/coordbench/track_b/` tree was removed; avoid importing it in tests or docs.

### Progress logging (“where is it stuck?”)

Added explicit `[Track B] phase i/6 ... overall xx%` progress lines so long API waits are distinguishable from a hang:
- flag → diagnose → sample → normalize → analyze → report

### Provider robustness: DeepSeek proxy + timeout issues

Observed failure mode:
- Environment had `http_proxy`/`https_proxy` set to an unreachable proxy; calls would time out and retry.

Fixes:
- `configs/study2_deepseek_s50.yaml` now sets `providers.deepseek.trust_env: false` so DeepSeek calls can bypass broken proxy settings.
- `src/coordbench/providers/deepseek_provider.py` now:
  - Uses an explicit `httpx.Client(..., trust_env=...)` based on provider `extra.trust_env` or `DEEPSEEK_TRUST_ENV`
  - Uses explicit read timeouts aligned to `timeout_seconds`

### Normalization behavior for Track B (unmapped answers)

Track B repair/sham prompts can produce short surface forms that do not pass strict canonical mapping at the default fuzzy threshold.

Fix:
- `normalize_run` now supports `allow_unmapped_override=...`
- Track B pipeline forces `allow_unmapped_override=True` so Track B doesn’t fail during normalization
- CLI also supports: `coordbench normalize ... --allow-unmapped`

### Packaging / docs / hygiene

- Track B YAML assets ship with the **`track-b-agent`** / `Agent` package; the main `coordbench` wheel does not duplicate them.
- `.env.example` was sanitized to remove real-looking keys and now documents `DEEPSEEK_TRUST_ENV`.
- Root `README.md` and `Agent/README.md` document the one-command flow and progress logs.

## What artifacts Track B produces

In each Track B run dir (e.g. `artifacts/runs/track_b_YYYYMMDDTHHMMSSZ/`):
- `flagged_items.json`, `unflagged_controls.json`, `track_b_manifest.json`
- `track_b_diagnoses.json`, `track_b_plan.json`
- `raw_generations.jsonl`
- `normalized_outputs.csv`, `unresolved_queue.csv`
- `item_metrics.csv`, `summary_metrics.json`, `bootstrap_intervals.csv`
- `track_b_report.md` (**main output**)

## Results summary (DeepSeek)

### Baseline used for the main confirmations

Primary baseline:
- `results/runs_s50/deepseek-v3.2_20260412T141541Z`

Alternate baseline for confirm:
- `results/runs_s50/deepseek-v3_20260412T121754Z`

Flagged items selected were consistent across baselines:
- `study2_item_03`
- `study2_item_12`
Controls used:
- `study2_item_01`, `study2_item_02`, `study2_item_06` (stable, JSD=0)

### Key headline: repair improves flagged cross-lingual JSD; sham does not

All runs below use:
- repair arm = round 3
- sham arm = round 4
- metric = cross-lingual JSD (`item_metrics.csv`, `metric_family=cross_lingual`, `prompt_language=en_vs_zh`)

#### Run 1 (initial successful full Track B)

Track run:
- `artifacts/runs/track_b_20260414T090524Z`

From `track_b_report.md`:
- **Flagged mean ΔJSD (repair vs baseline r1)**: **-0.1773** (n=2)
- **Flagged mean ΔJSD (sham vs baseline r1)**: **+0.0913** (n=2)

Per item:
- `study2_item_03`: r1 0.8164 → repair 0.6100 (Δ -0.2064) → sham 0.7573 (Δ -0.0591)
- `study2_item_12`: r1 0.7583 → repair 0.6100 (Δ -0.1483) → sham 1.0000 (Δ +0.2417)

Controls:
- all three controls stayed at JSD 0 across r1/r3/r4.

#### Repeatability check (same baseline, two repeats)

rep1:
- `artifacts/runs/track_b_20260414T092927Z`
  - Repair mean ΔJSD: **-0.1773**
  - Sham mean ΔJSD: **+0.0913**

rep2:
- `artifacts/runs/track_b_20260414T093001Z`
  - Repair mean ΔJSD: **-0.4564**
  - Sham mean ΔJSD: **+0.0913**

Notable observation:
- In `rep2`, `study2_item_12` received a different diagnosis/template (`R_SEM`) and achieved a much larger improvement:
  - r1 0.7583 → repair 0.0519 (Δ -0.7064)

#### Latest run (2026-04-14, DeepSeek v3.2 baseline, post-refactor layout)

Track run:
- `artifacts/runs/track_b_20260414T155044Z`

Baseline:
- `results/runs_s50/deepseek-v3.2_20260412T141541Z`

Execution notes:
- **Diagnosis**: live DeepSeek API (2 calls). Tags: `study2_item_03` → **T_LEAK** (`R_FMT`); `study2_item_12` → **T_SALIENCE** (`R_SEM`). Raw JSON lines are in `track_b_diagnoses.json` under the run dir.
- **Repair/sham sampling**: all **200** pending requests resolved from **`disk_cache`** (same deterministic requests as earlier full runs), so reported metrics match the “strong repair” branch below rather than re-querying the model for every sample.

From `track_b_report.md`:
- **Flagged mean ΔJSD (repair vs baseline r1)**: **-0.4564** (n=2)
- **Flagged mean ΔJSD (sham vs baseline r1)**: **+0.0913** (n=2)

Per item:
- `study2_item_03`: r1 0.8164 → repair 0.6100 (Δ -0.2064) → sham 0.7573 (Δ -0.0591)
- `study2_item_12`: r1 0.7583 → repair 0.0519 (Δ -0.7064) → sham 1.0000 (Δ +0.2417)

Controls: unchanged (JSD 0 across arms).

These numbers match **rep2** (`track_b_20260414T093001Z`) because diagnosis and cached completions align; the latest run mainly re-validates the integrated Agent path end-to-end.

Analysis (what this run adds):
- **Integration confidence**: It validates the post-refactor wiring end-to-end (core `coordbench` CLI → Agent pipeline → normalize/analyze → report) without reintroducing the prior path/import issues.
- **Result confidence (limited)**: Because the repair/sham generations were pulled from cache, this run should be treated as a **reproduction of previously-sampled outputs**, not an independent re-sampling of DeepSeek for the repair/sham arms.
- **New evidence from this run**: The **diagnosis tags** were freshly generated via DeepSeek and still landed on the same tag/template choices that correspond to the “strong repair” outcome (`T_SALIENCE → R_SEM` for `study2_item_12`), which is consistent with the earlier variance observation that diagnosis/template selection matters.
- **If you want a “true rerun”**: Clear the relevant `outputs.cache_root` entries (or point `UNIVERSAL_CACHE_ROOT` to a fresh directory) and rerun the same command so repair/sham hit the API rather than `disk_cache`.

#### Alternate-baseline confirmation (deepseek-v3 baseline)

Track run:
- `artifacts/runs/track_b_20260414T102304Z`
Baseline:
- `results/runs_s50/deepseek-v3_20260412T121754Z`

From `track_b_report.md`:
- Repair mean ΔJSD: **-0.2192**
- Sham mean ΔJSD: **+0.0495**

Per item:
- `study2_item_12`: r1 0.9290 → repair 0.6100 (Δ -0.3190) → sham 1.0000 (Δ +0.0710)
- `study2_item_03`: r1 0.7293 → repair 0.6100 (Δ -0.1194) → sham 0.7573 (Δ +0.0279)

### What this shows (interpretation)

- **Primary claim supported**: for flagged cross-lingual failures, the **diagnosis-driven repair arm** reduces cross-lingual divergence (ΔJSD < 0) while **sham** is not consistently improving (often ΔJSD > 0).
- **Control safety check**: controls remain stable (JSD≈0) across arms, suggesting the repair mechanism is not simply flattening outputs globally.
- **Template sensitivity**: `study2_item_12` shows large variance depending on diagnosis/template (`R_FMT` vs `R_SEM`), indicating diagnosis quality matters.
- **Cache caveat**: runs that report `source=disk_cache` for most/alls samples primarily validate **pipeline determinism and report correctness**; for a strict “model rerun” claim, re-run with an empty/new cache root.

## Suggested next confirmation (if desired)

To strengthen the “method not model-specific” claim:
- Run the same Track B pipeline on one additional provider/model (e.g., OpenAI or Gemini) with its own baseline run, and compare repair vs sham ΔJSD on that model’s flagged items.

