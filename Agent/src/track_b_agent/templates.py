from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_repair_templates(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_tag_to_repair(path: Path) -> dict[str, str]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in raw.items()}


def map_tag_to_repair(tag: str, tag_to_repair: dict[str, str]) -> str:
    return tag_to_repair.get(tag, "R_COORD")


def render_repair_template(
    template_id: str,
    *,
    prompt_language: str,
    templates: dict[str, Any],
    item_text_en: str,
    item_text_zh: str,
    answer_language: str,
    context_en: str,
    context_zh: str,
) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for EN or ZH prompt_language."""
    block = templates[template_id]
    if prompt_language == "zh":
        system = block["system_zh"].format(
            context_zh=context_zh,
            answer_language=answer_language,
            item_text_zh=item_text_zh,
            item_text_en=item_text_en,
            context_en=context_en,
        )
        user = block["user_zh"].format(
            context_zh=context_zh,
            answer_language=answer_language,
            item_text_zh=item_text_zh,
            item_text_en=item_text_en,
            context_en=context_en,
        )
    else:
        system = block["system_en"].format(
            context_en=context_en,
            answer_language=answer_language,
            item_text_en=item_text_en,
            item_text_zh=item_text_zh,
            context_zh=context_zh,
        )
        user = block["user_en"].format(
            context_en=context_en,
            answer_language=answer_language,
            item_text_en=item_text_en,
            item_text_zh=item_text_zh,
            context_zh=context_zh,
        )
    return system, user
