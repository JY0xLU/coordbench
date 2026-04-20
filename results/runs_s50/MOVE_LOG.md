# S50 Run Move Log (2026-04-12)

Moved completed 50-sample runs (with analysis artifacts) from `artifacts/full_experiments/.../runs/...` into `results/runs_s50/`, with folder names in `model_timestamp` format.

## Final Paths (`model_timestamp`)

- `results/runs_s50/gpt-4o-mini_20260412T115957Z`
- `results/runs_s50/gpt-5.4_20260412T043325Z`
- `results/runs_s50/deepseek-v3_20260412T121754Z`
- `results/runs_s50/deepseek-v3.2_20260412T141541Z`

## Original Artifact Paths

- `artifacts/full_experiments/20260412T_gpt-4o-mini_c4_s50/gpt-4o-mini/runs/20260412T115957Z`
- `artifacts/full_experiments/20260412T_gpt-5.4_c4_recheck4/gpt-5.4/runs/20260412T043325Z`
- `artifacts/full_experiments/20260412T_deepseek-v3_c4_s50/deepseek-chat/runs/20260412T121754Z`
- `artifacts/full_experiments/20260412T_deepseek-v3.2_c4_s50/deepseek-chat/runs/20260412T141541Z`

## Not Moved

- `deepseek-v1` run not moved because the run was incomplete.

## Added 2026-04-15

Moved completed 50-sample runs from the 2026-04-14 universal API full experiment batch into `results/runs_s50/`.

### Final Paths (`model_timestamp`)

- `results/runs_s50/gpt-5.4-mini_20260413T081755Z`
- `results/runs_s50/gpt-5.4_20260413T112311Z`
- `results/runs_s50/MiniMax-M2.7_20260414T105529Z`
- `results/runs_s50/kimi-for-coding_20260414T162518Z`

### Original Artifact Paths

- `artifacts/full_experiments/gpt54mini_s50_c3_20260413T161752Z/runs/20260413T081755Z`
- `artifacts/full_experiments/gpt54_s50_c3_20260413T192303Z/runs/20260413T112311Z`
- `artifacts/full_experiments/20260414T185527Z_MiniMax-M2.7_c10/runs/20260414T105529Z`
- `artifacts/full_experiments/20260414T162514Z_kimi-for-coding_c5/runs/20260414T162518Z`

### Notes

- Both runs reached `raw_record_count=1500`.
- `run_manifest.json` shows `normalization_completed=true` for both runs, but the outer `run-all` flow still raised because unresolved outputs remained.

## 2026-04-18 additional mirrors
- K2.6-code-preview_20260417T175310Z <- artifacts/full_experiments/20260418T015308Z_K2.6-code-preview_c15/K2.6-code-preview/runs/20260417T175310Z
- mimo-v2-omni_20260417T175954Z <- artifacts/full_experiments/20260418T020021Z_mimo-v2-omni_c20/mimo-v2-omni/runs/20260417T175954Z
- mimo-v2-pro_20260417T175955Z <- artifacts/full_experiments/20260418T020021Z_mimo-v2-pro_c20/mimo-v2-pro/runs/20260417T175955Z
- MiniMax-M2.7-highspeed_20260417T175955Z <- artifacts/full_experiments/20260418T020021Z_MiniMax-M2.7-highspeed_c15/MiniMax-M2.7-highspeed/runs/20260417T175955Z
- qwen3.6-plus_20260417T171417Z <- artifacts/full_experiments/20260418T011415Z_qwen3.6-plus_c5/qwen3.6-plus/runs/20260417T171417Z (resumed partial run; raw completed to 1500)
