from __future__ import annotations

import json
from pathlib import Path


def write_stub_diagnoses(out_dir: Path) -> int:
    """Write diagnosis/<item_id>.json with T_UNK for each flagged item (plan §4.4)."""
    flagged_path = out_dir / "flagged_items.json"
    if not flagged_path.exists():
        raise FileNotFoundError(flagged_path)
    flagged = json.loads(flagged_path.read_text(encoding="utf-8"))
    diag_dir = out_dir / "diagnosis"
    diag_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for rec in flagged:
        iid = rec["item_id"]
        payload = {
            "item_id": iid,
            "tags": ["T_UNK"],
            "evidence": "Stub: no LLM call (--diagnose-stub).",
            "confidence": "low",
        }
        (diag_dir / f"{iid}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        n += 1
    return n
