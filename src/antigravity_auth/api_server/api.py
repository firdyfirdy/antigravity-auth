import time
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from antigravity_auth import AntigravityService, NoAccountsError
from antigravity_auth.api_server.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionChoice,
    ChatMessage,
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionChunkDelta,
    ImageGenerationRequest,
    ImageGenerationResponse,
    ImageData,
)

app = FastAPI(title="Antigravity API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {"id": "gemini-3-pro", "object": "model", "created": 1677610602, "owned_by": "antigravity"},
            {"id": "gemini-3-pro-image", "object": "model", "created": 1677610602, "owned_by": "antigravity"},
            {"id": "gemini-3-flash", "object": "model", "created": 1677610602, "owned_by": "antigravity"},
            {"id": "gemini-2.5-pro", "object": "model", "created": 1677610602, "owned_by": "antigravity"},
            {"id": "gemini-2.5-flash", "object": "model", "created": 1677610602, "owned_by": "antigravity"},
            {"id": "claude-sonnet-4-5", "object": "model", "created": 1677610602, "owned_by": "antigravity"},
            {"id": "claude-opus-4-5", "object": "model", "created": 1677610602, "owned_by": "antigravity"},
        ]
    }

@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    try:
        service = AntigravityService(model=request.model)
        
        # Build prompt from messages
        # Simple concatenation for now (AntigravityService will handle role adaptation internally via its generate method logic if updated, 
        # or we manually format. Since service.generate expects a string prompt, let's format it).
        full_prompt = ""
        system_prompt = None
        
        for msg in request.messages:
            if msg.role == "system":
                system_prompt = msg.content
            else:
                full_prompt += f"{msg.role.upper()}: {msg.content}\n"
        
        if not full_prompt.strip():
             full_prompt = "Hello" # Fallback
             
        if request.stream:
             return StreamingResponse(
                 stream_generator(service, full_prompt, system_prompt, request.model),
                 media_type="text/event-stream"
             )
        else:
             response_text = await service.generate(prompt=full_prompt, system_prompt=system_prompt)
             return ChatCompletionResponse(
                 model=request.model,
                 choices=[
                     ChatCompletionChoice(
                         index=0,
                         message=ChatMessage(role="assistant", content=response_text),
                         finish_reason="stop"
                     )
                 ]
             )
             
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def stream_generator(service, prompt, system_prompt, model):
    """
    True real-time streaming generator.
    
    Yields SSE events as chunks arrive from the model in real-time.
    """
    try:
        async for chunk in service.generate_stream(
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
        ):
            response = ChatCompletionChunk(
                model=model,
                choices=[
                    ChatCompletionChunkChoice(
                        index=0,
                        delta=ChatCompletionChunkDelta(content=chunk),
                        finish_reason=None
                    )
                ]
            )
            yield f"data: {response.model_dump_json()}\n\n"
        
        # Final stop chunk
        final_response = ChatCompletionChunk(
            model=model,
            choices=[
                ChatCompletionChunkChoice(
                    index=0,
                    delta=ChatCompletionChunkDelta(content=""),
                    finish_reason="stop"
                )
            ]
        )
        yield f"data: {final_response.model_dump_json()}\n\n"
        yield "data: [DONE]\n\n"
        
    except Exception as e:
        # Send error as final chunk
        error_response = ChatCompletionChunk(
            model=model,
            choices=[
                ChatCompletionChunkChoice(
                    index=0,
                    delta=ChatCompletionChunkDelta(content=f"\n\n[Error: {str(e)}]"),
                    finish_reason="stop"
                )
            ]
        )
        yield f"data: {error_response.model_dump_json()}\n\n"
        yield "data: [DONE]\n\n"


# =============================================================================
# Image Generation Endpoints
# =============================================================================

def size_to_aspect_ratio(size: str) -> str:
    """
    Convert OpenAI-style size string to aspect ratio.

    Args:
        size: Size string like "1024x1024", "1792x1024", "1024x1792"

    Returns:
        Aspect ratio string like "1:1", "16:9", "9:16"
    """
    size_mapping = {
        "1024x1024": "1:1",
        "1792x1024": "16:9",
        "1024x1792": "9:16",
        "512x512": "1:1",
        "256x256": "1:1",
    }
    return size_mapping.get(size, "1:1")


@app.post("/v1/images/generations")
async def generate_images(request: ImageGenerationRequest):
    """
    Generate images from a text prompt (OpenAI-compatible endpoint).

    This endpoint is compatible with the OpenAI Images API.
    """
    try:
        service = AntigravityService(model=request.model)

        # Convert size to aspect ratio
        aspect_ratio = size_to_aspect_ratio(request.size or "1024x1024")

        # Generate image
        images = await service.generate_image(
            prompt=request.prompt,
            model=request.model,
            aspect_ratio=aspect_ratio,
        )

        # Convert to OpenAI-compatible response
        image_data_list = []
        for img in images:
            image_data_list.append(
                ImageData(
                    b64_json=img.get("data"),
                    revised_prompt=request.prompt,
                )
            )

        return ImageGenerationResponse(
            created=int(time.time()),
            data=image_data_list,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

