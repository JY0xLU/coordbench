from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "full_experiments"
POLL_SECONDS = 15


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with path.open("r", encoding="utf-8") as fh:
            return sum(1 for _ in fh)
    except Exception:  # noqa: BLE001
        return 0


def tail_text(path: Path, max_lines: int = 20) -> list[str]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-max_lines:]
    except Exception:  # noqa: BLE001
        return []


def latest_run_dir() -> Path | None:
    dirs = [p for p in ARTIFACT_ROOT.iterdir() if p.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda p: p.stat().st_mtime)


def build_status() -> dict[str, Any]:
    status: dict[str, Any] = {"captured_at": datetime.now(timezone.utc).isoformat()}
    run_dir = latest_run_dir()
    if run_dir is None:
        status["state"] = "no_run_dir"
        return status

    summary = read_json(run_dir / "summary.json")
    err_log = ARTIFACT_ROOT / f"{run_dir.name}.err.log"
    out_log = ARTIFACT_ROOT / f"{run_dir.name}.out.log"

    raw_candidates = list(run_dir.rglob("raw_generations.jsonl"))
    raw_path = max(raw_candidates, key=lambda p: p.stat().st_mtime) if raw_candidates else None

    status.update(
        {
            "state": "watching",
            "run_dir": str(run_dir),
            "run_name": run_dir.name,
            "summary_exists": summary is not None,
            "summary": summary,
            "raw_generations_path": str(raw_path) if raw_path else None,
            "raw_count": count_lines(raw_path) if raw_path else 0,
            "err_log": str(err_log) if err_log.exists() else None,
            "err_tail": tail_text(err_log),
            "out_log": str(out_log) if out_log.exists() else None,
            "out_tail": tail_text(out_log),
        }
    )
    return status


def main() -> int:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    latest_path = ARTIFACT_ROOT / "live_experiment_status.json"
    history_path = ARTIFACT_ROOT / "live_experiment_status.jsonl"

    while True:
        status = build_status()
        latest_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        with history_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(status, ensure_ascii=False) + "\n")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
