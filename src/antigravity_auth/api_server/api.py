import time
from typing import List, Optional
import asyncio
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
    # Determine which accounts to use 
    # NOTE: basic streaming simulation since AntigravityService might not support full streaming yet.
    # If AntigravityService supports streaming, we should use it.
    # Assuming standard generic generate currently returns full text.
    # We will simulate streaming for now to satisfy Client requirements if needed, 
    # OR better: Implement true streaming in AntigravityService later. 
    # For this MVP, let's await the response and chunk it (pseudo-streaming) or block.
    
    # Real implementation should call: async for chunk in service.generate_stream(...)
    
    response_text = await service.generate(prompt=prompt, system_prompt=system_prompt)
    
    # Chunk raw response
    chunk_size = 20
    for i in range(0, len(response_text), chunk_size):
        chunk = response_text[i:i+chunk_size]
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
        await asyncio.sleep(0.01) # Simulate network delay
        
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
