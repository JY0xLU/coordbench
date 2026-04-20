from pathlib import Path

from coordbench.config import load_config
from coordbench.prompts import build_prompt_messages, translate_item


def test_translate_item_has_known_mapping():
    assert translate_item("Name a city") == "说出一座城市"


def test_build_prompt_messages_round1():
    messages = build_prompt_messages(
        item_text_en="Name a city",
        item_text_zh="说出一座城市",
        prompt_language="zh",
        answer_language="English",
        round_index=1,
        target_group="british",
    )
    assert len(messages) == 2
    assert "English" in messages[1].content
    assert "说出一座城市" in messages[1].content
    assert "英国" in messages[0].content or "英国" in messages[1].content


def test_load_config_env_expansion(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "test-openai-model")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "providers:",
                "  openai:",
                "    enabled: true",
                "    model: ${OPENAI_MODEL}",
                "    api_key_env: OPENAI_API_KEY",
                "sampling:",
                "  panel_id: study2_british_within",
                "  answer_language: English",
                "  prompt_languages: [en, zh]",
                "  item_ids: [study2_item_01, study2_item_03]",
                "  round1_samples: 2",
                "  round2_samples: 1",
                "  enable_round2: true",
                "  round2_trigger: cross_lingual_top1_mismatch",
                "  random_seed: 1",
                "normalization:",
                "  allow_unmapped: true",
                "  fuzzy_match_threshold: 95",
                "analysis:",
                "  bootstrap_resamples: 10",
                "  item_bootstrap_resamples: 10",
            ]
        ),
        encoding="utf-8",
    )
    config = load_config(config_path)
    assert config.providers["openai"].model == "test-openai-model"
    assert config.sampling.item_ids == ["study2_item_01", "study2_item_03"]
