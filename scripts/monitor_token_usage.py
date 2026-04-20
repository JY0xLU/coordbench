from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "full_experiments"
USAGE_API_BASE = os.environ.get("TOKENLAND_API_BASE", "https://api.mytokenland.com").rstrip("/")
POLL_SECONDS = 60


def load_env() -> None:
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def auth_headers() -> dict[str, str]:
    key = str(os.environ.get("UNIVERSAL_API_KEY", "")).strip()
    return {"Authorization": f"Bearer {key}"} if key else {}


def fetch_json(session: requests.Session, path: str) -> Any:
    response = session.get(f"{USAGE_API_BASE}{path}", headers=auth_headers(), timeout=30)
    response.raise_for_status()
    return response.json()


def main() -> int:
    load_env()
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)

    run_tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = ARTIFACT_ROOT / f"token_usage_monitor_{run_tag}.jsonl"
    heartbeat_path = ARTIFACT_ROOT / "token_usage_monitor.latest.json"

    session = requests.Session()
    session.trust_env = False

    while True:
        now = datetime.now(timezone.utc)
        record: dict[str, Any] = {"captured_at": now.isoformat()}
        try:
            record["usage"] = fetch_json(session, "/api/usage/token/")
        except Exception as exc:  # noqa: BLE001
            record["usage_error"] = str(exc)
        try:
            record["logs"] = fetch_json(session, "/api/log/token")
        except Exception as exc:  # noqa: BLE001
            record["logs_error"] = str(exc)

        with output_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        heartbeat_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
