# Results Layout

Current structure is split into two roots:

- `previous/`
  - Archived historical outputs grouped by experiment type:
    - `previous/full_experiments/`
    - `previous/stability_probes/`
    - `previous/concurrency_sweeps/`
    - `previous/reports/`
    - `previous/runs/` (legacy mirrored run folders)
- `runs_s50/`
  - Curated post-code-update 50-sample run folders.
  - Naming convention: `model_timestamp` (for example `gpt-5.4_20260412T043325Z`).
  - Includes temperature sensitivity set under `runs_s50/temp_test_20260412_gpt5.4/`.

## Where Raw Run Artifacts Live

Primary raw run artifacts remain under `artifacts/`:

- `artifacts/runs/<run_id>/...`
- `artifacts/full_experiments/<root_tag>/...`
- `artifacts/stability_probes/<batch_tag>/...`
- `artifacts/sweeps/<sweep_tag>/...`

Selected finalized runs are mirrored into `results/runs_s50/` for reporting convenience (without provider cache folders).
