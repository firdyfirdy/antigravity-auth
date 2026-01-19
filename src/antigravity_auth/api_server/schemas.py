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


# =============================================================================
# Image Generation Schemas (OpenAI-compatible)
# =============================================================================

class ImageGenerationRequest(BaseModel):
    """Request schema for image generation (OpenAI-compatible)."""
    prompt: str
    model: str = "gemini-3-pro-image"
    n: int = 1  # Number of images (only 1 supported for now)
    size: Optional[str] = "1024x1024"  # Maps to aspect ratio
    response_format: str = "b64_json"  # b64_json or url
    quality: Optional[str] = None  # Not used but accepted for compatibility
    style: Optional[str] = None  # Not used but accepted for compatibility


class ImageData(BaseModel):
    """Individual image data in response."""
    b64_json: Optional[str] = None  # Base64 encoded image data
    url: Optional[str] = None  # URL if saved to disk
    revised_prompt: Optional[str] = None  # The prompt that was used


class ImageGenerationResponse(BaseModel):
    """Response schema for image generation (OpenAI-compatible)."""
    created: int = Field(default_factory=lambda: 0)
    data: List[ImageData]
