from gateway.core.schema import ChatCompletionRequest, Message


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
