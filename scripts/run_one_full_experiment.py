from __future__ import annotations

import argparse
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MPL_DIR = REPO_ROOT / "artifacts" / "mplconfig"
MPL_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(MPL_DIR))

from run_universal_full_experiments import ARTIFACT_ROOT, _run_model, _write_summary


def _load_local_env(repo_root: Path) -> None:
    env_path = repo_root / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value)
def main() -> int:
    parser = argparse.ArgumentParser(description="Run one full CoordBench experiment for a single model.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--concurrency", required=True, type=int)
    parser.add_argument("--root-tag", required=True)
    args = parser.parse_args()

    _load_local_env(REPO_ROOT)

    root_dir = ARTIFACT_ROOT / args.root_tag
    root_dir.mkdir(parents=True, exist_ok=True)

    row = _run_model(root_dir, args.model, args.concurrency)
    json_path, md_path = _write_summary(root_dir, [row])

    print(f"model={args.model}")
    print(f"concurrency={args.concurrency}")
    print(f"status={row.status}")
    print(f"summary_json={json_path}")
    print(f"summary_md={md_path}")
    print(f"run_dir={row.run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
