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

    temperature: Optional[float]
    stream: Optional[bool]
    max_tokens: Optional[int]

class Usage(BaseModel):
    """Token counts — this is what Budget settles against."""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

class ChatCompletionResponse(BaseModel):
    """
    Represents a response from a chat completion request.
    """
    model: str
    full_response: Optional[str]
    delta: Optional[str]
    finish_reason: Optional[str] = None
    usage: Optional[Usage] = None


