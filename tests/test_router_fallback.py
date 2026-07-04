from gateway.core.schema import ChatCompletionRequest, Message
from gateway.router.router import build_fallback_candidates, is_retryable_status, NoProviderAvailableError


def test_chat_completion_request_fallback_flags_default_false():
    request = ChatCompletionRequest(
        model="gpt-4o",
        messages=[Message(role="user", content="hi")],
    )
    assert request.allow_fallback is False
    assert request.allow_tier_downgrade is False


def test_chat_completion_request_fallback_flags_can_be_set():
    request = ChatCompletionRequest(
        model="gpt-4o",
        messages=[Message(role="user", content="hi")],
        allow_fallback=True,
        allow_tier_downgrade=True,
    )
    assert request.allow_fallback is True
    assert request.allow_tier_downgrade is True


ALLOWED_MODELS = [
    {"name": "gpt-4o", "provider": "openai", "cost_per_input_token": 0.0000025, "cost_per_output_token": 0.00001, "tier": 4},
    {"name": "claude-sonnet", "provider": "anthropic", "cost_per_input_token": 0.000003, "cost_per_output_token": 0.000015, "tier": 4},
    {"name": "gemini-pro", "provider": "gemini", "cost_per_input_token": 0.000002, "cost_per_output_token": 0.000008, "tier": 4},
    {"name": "gpt-4o-mini", "provider": "openai", "cost_per_input_token": 0.00000015, "cost_per_output_token": 0.0000006, "tier": 2},
    {"name": "llama3", "provider": "ollama", "cost_per_input_token": 0.0, "cost_per_output_token": 0.0, "tier": 2},
]


def test_same_tier_excludes_failed_provider():
    candidates = build_fallback_candidates("gpt-4o", ALLOWED_MODELS, failed_provider="openai", allow_tier_downgrade=False)
    providers = {c["provider"] for c in candidates}
    tiers = {c["tier"] for c in candidates}
    assert "openai" not in providers
    assert tiers == {4}
    assert providers == {"anthropic", "gemini"}


def test_no_tier_downgrade_stops_at_same_tier():
    candidates = build_fallback_candidates("gpt-4o", ALLOWED_MODELS, failed_provider="openai", allow_tier_downgrade=False)
    assert all(c["tier"] == 4 for c in candidates)


def test_tier_downgrade_includes_lower_tier():
    candidates = build_fallback_candidates("gpt-4o", ALLOWED_MODELS, failed_provider="openai", allow_tier_downgrade=True)
    tiers = {c["tier"] for c in candidates}
    assert tiers == {4, 2}
    tier_2 = [c for c in candidates if c["tier"] == 2]
    assert {c["provider"] for c in tier_2} == {"ollama"}  # gpt-4o-mini excluded: same provider as the original failure


def test_candidates_never_repeat_a_provider():
    candidates = build_fallback_candidates("gpt-4o", ALLOWED_MODELS, failed_provider="openai", allow_tier_downgrade=True)
    providers = [c["provider"] for c in candidates]
    assert len(providers) == len(set(providers))


def test_candidates_exclude_requested_model_itself():
    candidates = build_fallback_candidates("gpt-4o", ALLOWED_MODELS, failed_provider="openai", allow_tier_downgrade=True)
    assert all(c["name"] != "gpt-4o" for c in candidates)


def test_no_candidates_when_requested_model_unknown():
    candidates = build_fallback_candidates("not-in-list", ALLOWED_MODELS, failed_provider="openai", allow_tier_downgrade=True)
    assert candidates == []


def test_no_candidates_when_tier_exhausted_and_no_downgrade():
    single_tier_models = [
        {"name": "gpt-4o", "provider": "openai", "cost_per_input_token": 0.0, "cost_per_output_token": 0.0, "tier": 4},
    ]
    candidates = build_fallback_candidates("gpt-4o", single_tier_models, failed_provider="openai", allow_tier_downgrade=False)
    assert candidates == []


def test_retryable_status_codes():
    for code in (429, 500, 502, 503, 504):
        assert is_retryable_status(code) is True


def test_non_retryable_status_codes():
    for code in (400, 401, 403, 422):
        assert is_retryable_status(code) is False


def test_unlisted_status_code_is_not_retryable():
    for code in (404, 405, 408, 409, 418):
        assert is_retryable_status(code) is False


def test_no_provider_available_error_is_an_exception():
    assert issubclass(NoProviderAvailableError, Exception)
