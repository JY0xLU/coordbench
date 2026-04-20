from coordbench.models import GenerationRequest, ProviderConfig
from coordbench.providers.gemini_provider import GeminiProvider


class _FakeCandidate:
    def __init__(self, finish_reason):
        self.finish_reason = finish_reason


class _FakeUsage:
    prompt_token_count = 10
    candidates_token_count = 3
    total_token_count = 13


class _FakeResponse:
    text = "London"
    model_version = "gemini-2.5-flash"
    response_id = "gemini_resp_123"
    usage_metadata = _FakeUsage()
    candidates = [_FakeCandidate("MAX_TOKENS")]

    def model_dump(self):
        return {
            "text": self.text,
            "model_version": self.model_version,
            "response_id": self.response_id,
            "candidates": [{"finish_reason": "MAX_TOKENS"}],
        }


class _FakeModels:
    def generate_content(self, **kwargs):
        return _FakeResponse()


class _FakeClient:
    models = _FakeModels()


def test_gemini_provider_records_finish_reason(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    config = ProviderConfig(
        enabled=True,
        model="gemini-2.5-flash",
        api_key_env="GEMINI_API_KEY",
        timeout_seconds=30,
    )
    provider = GeminiProvider(config)
    provider.client = _FakeClient()
    request = GenerationRequest(
        provider="gemini",
        model="gemini-2.5-flash",
        panel_id="study2_british_within",
        item_id="study2_item_01",
        item_text_en="Name a city",
        item_text_zh="city zh",
        prompt_language="en",
        answer_language="English",
        round_index=1,
        sample_index=0,
        system_prompt="Return one answer only.",
        user_prompt="Category: Name a city",
        temperature=1.0,
        max_output_tokens=24,
    )

    response = provider.generate(request)

    assert response.text == "London"
    assert response.finish_reason == "MAX_TOKENS"
