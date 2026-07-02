def estimate_tokens(text: str) -> int:
    """1 token ~= 4 characters. Used wherever a real, provider-reported token
    count isn't available yet (pre-call estimates, in-flight streaming chunks)."""
    return len(text) // 4
