from coordbench.models import GenerationRequest, ProviderConfig
from coordbench.providers.anthropic_provider import AnthropicProvider


class _FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "id": "msg_test",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "London"}],
            "usage": {"input_tokens": 10, "output_tokens": 3},
        }


class _FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, timeout, headers, json):
        self.calls.append(
            {
                "url": url,
                "timeout": timeout,
                "headers": headers,
                "json": json,
            }
        )
        return _FakeResponse()


def test_anthropic_provider_payload(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "secret")
    config = ProviderConfig(
        enabled=True,
        model="claude-opus-4-5",
        api_key_env="ANTHROPIC_AUTH_TOKEN",
        timeout_seconds=30,
        extra={"base_url": "https://api.example.com", "anthropic_version": "2023-06-01"},
    )
    provider = AnthropicProvider(config)
    fake_session = _FakeSession()
    provider.session = fake_session
    request = GenerationRequest(
        provider="anthropic",
        model="claude-opus-4-5",
        panel_id="study2_british_within",
        item_id="study2_item_01",
        item_text_en="Name a city",
        item_text_zh="说出一座城市",
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
    assert fake_session.calls[0]["url"] == "https://api.example.com/v1/messages"
    assert fake_session.calls[0]["json"]["model"] == "claude-opus-4-5"


def test_anthropic_provider_openai_compat(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "secret")
    config = ProviderConfig(
        enabled=True,
        model="claude-opus-4-6",
        api_key_env="ANTHROPIC_AUTH_TOKEN",
        timeout_seconds=30,
        extra={"base_url": "https://api.example.com", "compat_mode": "openai"},
    )
    provider = AnthropicProvider(config)

    class _CompatResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "id": "chatcmpl_test",
                "choices": [{"message": {"content": "London"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
            }

    class _CompatSession:
        def __init__(self):
            self.calls = []

        def post(self, url, timeout, headers, json):
            self.calls.append({"url": url, "timeout": timeout, "headers": headers, "json": json})
            return _CompatResponse()

    fake_session = _CompatSession()
    provider.session = fake_session
    request = GenerationRequest(
        provider="anthropic",
        model="claude-opus-4-6",
        panel_id="study2_british_within",
        item_id="study2_item_01",
        item_text_en="Name a city",
        item_text_zh="说出一座城市",
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
    assert fake_session.calls[0]["url"] == "https://api.example.com/v1/chat/completions"
