from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from coordbench.prompts import _target_group_context_en, _target_group_context_zh


def load_repair_templates(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_tag_to_repair(path: Path) -> dict[str, str]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): str(v) for k, v in raw.items() if k and v}


def repair_template_for_tag(tag: str, mapping: dict[str, str]) -> str:
    return mapping.get(tag.strip().upper(), "R_COORD")


def render_arm_prompts(
    templates: dict[str, Any],
    template_key: str,
    *,
    prompt_language: str,
    answer_language: str,
    item_text_en: str,
    item_text_zh: str,
    target_group: str,
) -> tuple[str, str]:
    block = templates.get(template_key)
    if not isinstance(block, dict):
        raise KeyError(f"Unknown repair template: {template_key}")

    context_en = _target_group_context_en(target_group)
    context_zh = _target_group_context_zh(target_group)
    fmt = {
        "answer_language": answer_language,
        "item_text_en": item_text_en,
        "item_text_zh": item_text_zh,
        "context_en": context_en,
        "context_zh": context_zh,
    }
    pl = prompt_language.lower()
    if pl == "zh":
        system = str(block["system_zh"]).format(**fmt)
        user = str(block["user_zh"]).format(**fmt)
    else:
        system = str(block["system_en"]).format(**fmt)
        user = str(block["user_en"]).format(**fmt)
    return system, user

