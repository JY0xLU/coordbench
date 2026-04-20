"""Frozen protocol constants (agent_plan.md §7.1, §8)."""

TRACK_B_BASELINE = "track_a_round1_only"

VALID_DIAGNOSIS_TAGS = frozenset(
    {
        "T_TRANS",
        "T_CULT",
        "T_LEAK",
        "T_LEX",
        "T_FRAG",
        "T_LITERAL",
        "T_SALIENCE",
        "T_UNK",
    }
)

REPAIR_TEMPLATE_IDS = frozenset({"R_SEM", "R_FMT", "R_COORD", "R_SHAM"})

# Payload keys permitted in diagnosis / repair render inputs (allowlist audit)
DIAGNOSIS_INPUT_ALLOWLIST = frozenset(
    {
        "item_id",
        "item_text_en",
        "item_text_zh",
        "answer_language",
        "prompt_language",
        "model_topk_en",
        "model_topk_zh",
        "system_prompt_en",
        "system_prompt_zh",
        "user_prompt_en",
        "user_prompt_zh",
    }
)

# Substrings that must not appear in serialized LLM payloads (blacklist layer)
AUDIT_BLACKLIST_SUBSTRINGS = (
    "human_distributions",
    "participant_responses",
    "human_top1_probability",
    "consensus_bucket",
    "probability",
    "most people",
    "大多数人类",
    "众数",
    "ground truth",
)
