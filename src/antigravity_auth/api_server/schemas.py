from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatCompletionRequest(BaseModel):
    model: str = "gemini-3-pro"
    messages: List[ChatMessage]
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None

class ChatCompletionChoice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: Optional[str] = "stop"

class ChatCompletionChunkDelta(BaseModel):
    role: Optional[str] = None
    content: Optional[str] = None

class ChatCompletionChunkChoice(BaseModel):
    index: int
    delta: ChatCompletionChunkDelta
    finish_reason: Optional[str] = None

class ChatCompletionResponse(BaseModel):
    id: str = Field(default_factory=lambda: "chatcmpl-antigravity")
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: 0)
    model: str
    choices: List[ChatCompletionChoice]
    usage: Optional[Dict[str, int]] = None

class ChatCompletionChunk(BaseModel):
    id: str = Field(default_factory=lambda: "chatcmpl-antigravity")
    object: str = "chat.completion.chunk"
    created: int = Field(default_factory=lambda: 0)
    model: str
    choices: List[ChatCompletionChunkChoice]
