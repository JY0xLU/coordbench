from coordbench.response_validation import looks_like_service_error, response_validation_error
from coordbench.utils.text import extract_first_answer_line


def test_extract_first_answer_line_prefers_final_answer_after_think_block():
    value = "<think>\nI should reason first.\n</think>\n\nLondon"
    assert extract_first_answer_line(value) == "London"


def test_extract_first_answer_line_rejects_truncated_reasoning():
    value = "Thinking Process:\n\n1. Analyze the request."
    assert extract_first_answer_line(value) == ""


def test_response_validation_rejects_service_error_text():
    value = "\u6a21\u578b\u300cQwen\u300d\u7684\u8bf7\u6c42\u8d1f\u8f7d\u8fc7\u9ad8\uff0c\u8bf7\u7a0d\u540e\u518d\u8bd5\u3002"
    assert looks_like_service_error(value) is True
    assert response_validation_error(text=value) is not None


def test_response_validation_rejects_empty_and_accepts_plain_answer():
    assert response_validation_error(text="") == "empty response text"
    assert response_validation_error(text="London", finish_reason="stop") is None


def test_response_validation_rejects_truncated_partial_answer():
    assert (
        response_validation_error(
            text="Harry Potter and the Philosopher's",
            finish_reason="MAX_TOKENS",
        )
        == "response was truncated before a final answer was produced"
    )


def test_response_validation_accepts_short_answer_when_truncated():
    """Coordination answers often finish before trailing text hits max_tokens."""
    assert response_validation_error(text="London", finish_reason="length") is None
