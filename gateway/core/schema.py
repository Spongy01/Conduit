"""Pydantic models shared across the gateway: the provider-agnostic
request/response shapes every BaseProvider subclass converts to and from."""
from pydantic import BaseModel
from typing import Literal, Optional , List
class Message(BaseModel):
    """
    Represents a message to be sent via a provider.
    """
    role: Literal["system", "user", "assistant", "tool"]
    content: str

class ChatCompletionRequest(BaseModel):
    """
    Represents a request for a chat completion.
    """
    model: str
    messages: List[Message]

    temperature: float = 0.7
    stream: bool = False
    max_tokens: int = 200

class Usage(BaseModel):
    """Token counts — this is what Budget settles against."""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

class ChatCompletionResponse(BaseModel):
    """
    Represents a response from a chat completion request. Non-streaming
    calls yield one response with full_response set; streaming calls yield
    many with delta set, followed by a final usage-only chunk (is_final=True).
    """
    model: str
    full_response: Optional[str]= None
    delta: Optional[str] = None
    finish_reason: Optional[str] = None
    usage: Optional[Usage] = None
    is_final: bool = False


