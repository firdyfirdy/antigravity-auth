"""
Antigravity HTTP Client

This module handles HTTP requests to the Antigravity API, including
URL transformation, header injection, endpoint fallback, and response handling.
"""

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import httpx

from .constants import (
    ANTIGRAVITY_DEFAULT_PROJECT_ID,
    ANTIGRAVITY_ENDPOINT_FALLBACKS,
    ANTIGRAVITY_HEADERS,
    ANTIGRAVITY_SYSTEM_INSTRUCTION,
    GEMINI_CLI_ENDPOINT,
    GEMINI_CLI_HEADERS,
    HEADER_STYLE_ANTIGRAVITY,
    HEADER_STYLE_GEMINI_CLI,
    MODEL_FAMILY_CLAUDE,
    MODEL_FAMILY_GEMINI,
)


@dataclass
class PreparedRequest:
    """A prepared Antigravity API request."""
    url: str
    method: str
    headers: Dict[str, str]
    body: str
    streaming: bool
    requested_model: str
    effective_model: str
    project_id: str
    endpoint: str
    session_id: Optional[str] = None


@dataclass
class AntigravityResponse:
    """Response from the Antigravity API."""
    success: bool
    status_code: int
    headers: Dict[str, str]
    body: Any
    error: Optional[str] = None
    retry_after_ms: Optional[int] = None


def get_model_family(model: str) -> str:
    """
    Determine the model family from a model name.
    
    Args:
        model: Model name
        
    Returns:
        Model family (gemini or claude)
    """
    lower_model = model.lower()
    
    if "claude" in lower_model or "opus" in lower_model or "sonnet" in lower_model:
        return MODEL_FAMILY_CLAUDE
    
    return MODEL_FAMILY_GEMINI


def get_header_style_from_model(model: str) -> str:
    """
    Determine the header style based on model name.
    
    Quota routing:
    - Claude/GPT models -> Antigravity (only exist on Antigravity)
    - Models with :antigravity suffix -> Antigravity
    - Gemini 3 models (without -preview suffix) -> Antigravity (legacy backward compat)
    - Other models -> Gemini CLI (default)
    
    Args:
        model: Model name
        
    Returns:
        Header style
    """
    lower = model.lower()
    family = get_model_family(model)
    
    # Claude models always use Antigravity
    if family == MODEL_FAMILY_CLAUDE:
        return HEADER_STYLE_ANTIGRAVITY
    
    # Explicit :antigravity suffix
    if ":antigravity" in lower:
        return HEADER_STYLE_ANTIGRAVITY
    
    # Gemini 3 models use Antigravity quota (legacy backward compat)
    # Exception: -preview suffix uses Gemini CLI (e.g., gemini-3-pro-preview)
    if "gemini-3" in lower and "-preview" not in lower:
        return HEADER_STYLE_ANTIGRAVITY
    
    return HEADER_STYLE_GEMINI_CLI


# Tier regex for thinking models
TIER_REGEX = re.compile(r"-(minimal|low|medium|high)$", re.IGNORECASE)

# Default thinking levels for Gemini 3 models
GEMINI_3_DEFAULT_TIER = "low"


def resolve_gemini3_model(model: str) -> tuple[str, Optional[str]]:
    """
    Resolve Gemini 3 model name and thinking level.
    
    Gemini 3 Pro: Needs tier suffix (gemini-3-pro-low, gemini-3-pro-high)
    Gemini 3 Flash: Uses bare name + thinkingLevel param
    
    Args:
        model: Model name
        
    Returns:
        Tuple of (resolved_model_name, thinking_level)
    """
    lower = model.lower()
    
    # Not a Gemini 3 model
    if "gemini-3" not in lower:
        return model, None
    
    # Check for tier suffix
    tier_match = TIER_REGEX.search(model)
    tier = tier_match.group(1).lower() if tier_match else None
    base_name = TIER_REGEX.sub("", model) if tier else model
    
    is_pro = "gemini-3-pro" in lower
    is_flash = "gemini-3-flash" in lower
    
    if is_pro:
        # Gemini 3 Pro needs tier suffix for Antigravity API
        if tier:
            # Keep the original model name with tier
            return model, tier
        else:
            # Append default tier
            return f"{base_name}-{GEMINI_3_DEFAULT_TIER}", GEMINI_3_DEFAULT_TIER
    
    if is_flash:
        # Gemini 3 Flash uses bare name + thinkingLevel param
        return base_name, tier or GEMINI_3_DEFAULT_TIER
    
    # Other Gemini 3 models (if any)
    return model, tier


def strip_model_suffix(model: str) -> str:
    """
    Remove the :antigravity suffix from a model name.
    
    Args:
        model: Model name with potential suffix
        
    Returns:
        Clean model name
    """
    return re.sub(r":antigravity$", "", model, flags=re.IGNORECASE)


def prepare_request(
    model: str,
    contents: List[Dict[str, Any]],
    access_token: str,
    project_id: Optional[str] = None,
    endpoint: Optional[str] = None,
    header_style: Optional[str] = None,
    system_instruction: Optional[str] = None,
    generation_config: Optional[Dict[str, Any]] = None,
    streaming: bool = True,
) -> PreparedRequest:
    """
    Prepare a request for the Antigravity API.
    
    Args:
        model: Model name (e.g., "gemini-2.5-pro", "gemini-3-pro")
        contents: Conversation contents in Gemini format
        access_token: OAuth access token
        project_id: Antigravity project ID
        endpoint: Override endpoint URL
        header_style: Override header style
        system_instruction: Optional system instruction
        generation_config: Optional generation config
        streaming: Whether to use streaming
        
    Returns:
        PreparedRequest ready for execution
    """
    # Strip :antigravity suffix first
    model_clean = strip_model_suffix(model)
    
    # Resolve Gemini 3 model name and thinking level
    effective_model, thinking_level = resolve_gemini3_model(model_clean)
    
    effective_project_id = project_id or ANTIGRAVITY_DEFAULT_PROJECT_ID
    effective_header_style = header_style or get_header_style_from_model(model)
    
    # Select endpoint
    if endpoint:
        effective_endpoint = endpoint
    elif effective_header_style == HEADER_STYLE_GEMINI_CLI:
        effective_endpoint = GEMINI_CLI_ENDPOINT
    else:
        effective_endpoint = ANTIGRAVITY_ENDPOINT_FALLBACKS[0]
    
    # Build the Antigravity-style URL
    action = "streamGenerateContent" if streaming else "generateContent"
    url = f"{effective_endpoint}/v1internal:{action}"
    if streaming:
        url += "?alt=sse"
    
    # Build generation config with thinking level for Gemini 3
    gen_config = dict(generation_config) if generation_config else {}
    
    if thinking_level and "gemini-3" in effective_model.lower():
        # Add thinkingConfig for Gemini 3 models
        gen_config["thinkingConfig"] = {
            "includeThoughts": True,
            "thinkingLevel": thinking_level,
        }
    
    # Build request body
    inner_request = {
        "contents": contents,
    }
    
    if gen_config:
        inner_request["generationConfig"] = gen_config
    
    # Inject systemInstruction with role="user" (required for Antigravity compatibility)
    # Per CLIProxyAPI v6.6.89: must prepend ANTIGRAVITY_SYSTEM_INSTRUCTION
    if effective_header_style == HEADER_STYLE_ANTIGRAVITY:
        # For Antigravity quota, inject the required system instruction
        if system_instruction:
            # Prepend Antigravity instruction to user's instruction
            combined_instruction = ANTIGRAVITY_SYSTEM_INSTRUCTION + "\n\n" + system_instruction
        else:
            combined_instruction = ANTIGRAVITY_SYSTEM_INSTRUCTION
        
        inner_request["systemInstruction"] = {
            "role": "user",
            "parts": [{"text": combined_instruction}]
        }
    elif system_instruction:
        # For Gemini CLI quota, just use user's instruction
        inner_request["systemInstruction"] = {
            "parts": [{"text": system_instruction}]
        }
    
    # Wrap in Antigravity format
    wrapped_body = {
        "project": effective_project_id,
        "model": effective_model,
        "request": inner_request,
        "requestType": "agent",
        "userAgent": "antigravity",
        "requestId": f"agent-{uuid.uuid4()}",
    }
    
    # Select headers
    if effective_header_style == HEADER_STYLE_GEMINI_CLI:
        selected_headers = GEMINI_CLI_HEADERS
    else:
        selected_headers = ANTIGRAVITY_HEADERS
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if streaming else "application/json",
        **selected_headers,
    }
    
    return PreparedRequest(
        url=url,
        method="POST",
        headers=headers,
        body=json.dumps(wrapped_body),
        streaming=streaming,
        requested_model=model,
        effective_model=effective_model,
        project_id=effective_project_id,
        endpoint=effective_endpoint,
        session_id=f"session-{uuid.uuid4()}",
    )


def parse_retry_after(response: httpx.Response) -> Optional[int]:
    """
    Extract retry-after value from response headers or body.
    
    Args:
        response: HTTP response
        
    Returns:
        Retry delay in milliseconds or None
    """
    # Check headers
    retry_after_ms = response.headers.get("retry-after-ms")
    if retry_after_ms:
        try:
            return int(retry_after_ms)
        except ValueError:
            pass
    
    retry_after = response.headers.get("retry-after")
    if retry_after:
        try:
            return int(retry_after) * 1000
        except ValueError:
            pass
    
    # Try to parse from body
    try:
        body = response.json()
        error = body.get("error", {})
        details = error.get("details", [])
        
        for detail in details:
            if isinstance(detail, dict):
                # Check RetryInfo
                if "type.googleapis.com/google.rpc.RetryInfo" in detail.get("@type", ""):
                    retry_delay = detail.get("retryDelay", "")
                    if isinstance(retry_delay, str):
                        match = re.match(r"(\d+(?:\.\d+)?)(s|m|h)?", retry_delay)
                        if match:
                            value = float(match.group(1))
                            unit = match.group(2) or "s"
                            if unit == "h":
                                return int(value * 3600 * 1000)
                            elif unit == "m":
                                return int(value * 60 * 1000)
                            else:
                                return int(value * 1000)
                
                # Check quota metadata
                metadata = detail.get("metadata", {})
                quota_delay = metadata.get("quotaResetDelay")
                if quota_delay:
                    match = re.match(r"(\d+(?:\.\d+)?)(s|m|h)?", quota_delay)
                    if match:
                        value = float(match.group(1))
                        unit = match.group(2) or "s"
                        if unit == "h":
                            return int(value * 3600 * 1000)
                        elif unit == "m":
                            return int(value * 60 * 1000)
                        else:
                            return int(value * 1000)
    except Exception:
        pass
    
    return None


def parse_sse_response(text: str) -> List[Dict[str, Any]]:
    """
    Parse a Server-Sent Events response into individual events.
    
    Args:
        text: Raw SSE response text
        
    Returns:
        List of parsed JSON objects
    """
    events = []
    
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("data:"):
            data = line[5:].strip()
            if data and data != "[DONE]":
                try:
                    events.append(json.loads(data))
                except json.JSONDecodeError:
                    pass
    
    return events


def extract_text_from_response(response_body: Any, streaming: bool = False) -> str:
    """
    Extract text content from an Antigravity API response.
    
    For thinking models (Gemini 3, Claude thinking), parts may contain:
    - {"text": "..."} - Regular text content (extract this)
    - {"thought": "..."} - Thinking content (skip this)
    
    Args:
        response_body: Parsed response body
        streaming: Whether this was a streaming response
        
    Returns:
        Extracted text content
    """
    def extract_text_from_parts(parts: list) -> str:
        """Extract text from parts, skipping thinking blocks."""
        texts = []
        for part in parts:
            # Only extract regular text, not thoughts
            if isinstance(part, dict) and "text" in part and "thought" not in part:
                texts.append(part["text"])
        return "".join(texts)
    
    if streaming and isinstance(response_body, list):
        # Combine text from all streaming events
        texts = []
        for event in response_body:
            inner = event.get("response", event)
            candidates = inner.get("candidates", [])
            for candidate in candidates:
                content = candidate.get("content", {})
                parts = content.get("parts", [])
                text = extract_text_from_parts(parts)
                if text:
                    texts.append(text)
        return "".join(texts)
    
    # Non-streaming response
    if isinstance(response_body, dict):
        inner = response_body.get("response", response_body)
        candidates = inner.get("candidates", [])
        if candidates:
            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            return extract_text_from_parts(parts)
    
    return ""


class AntigravityClient:
    """
    HTTP client for making requests to the Antigravity API.
    
    Handles token injection, endpoint fallback, and rate limit detection.
    """
    
    def __init__(
        self,
        timeout: float = 300.0,
        max_retries: int = 3,
    ):
        """
        Initialize the Antigravity client.
        
        Args:
            timeout: Request timeout in seconds
            max_retries: Maximum number of endpoint fallback retries
        """
        self.timeout = timeout
        self.max_retries = max_retries
    
    async def execute(
        self,
        request: PreparedRequest,
        fallback_endpoints: Optional[List[str]] = None,
    ) -> AntigravityResponse:
        """
        Execute a prepared request with endpoint fallback.
        
        Args:
            request: PreparedRequest to execute
            fallback_endpoints: Optional list of fallback endpoints
            
        Returns:
            AntigravityResponse with results
        """
        endpoints = fallback_endpoints or ANTIGRAVITY_ENDPOINT_FALLBACKS
        last_error = None
        
        for endpoint in endpoints:
            # Update URL for this endpoint
            url = request.url
            for ep in ANTIGRAVITY_ENDPOINT_FALLBACKS + [GEMINI_CLI_ENDPOINT]:
                if ep in url:
                    url = url.replace(ep, endpoint)
                    break
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                try:
                    response = await client.request(
                        method=request.method,
                        url=url,
                        headers=request.headers,
                        content=request.body,
                    )
                    
                    # Handle rate limiting
                    if response.status_code == 429:
                        retry_after = parse_retry_after(response) or 60000
                        return AntigravityResponse(
                            success=False,
                            status_code=429,
                            headers=dict(response.headers),
                            body=response.json() if response.text else {},
                            error="Rate limited",
                            retry_after_ms=retry_after,
                        )
                    
                    # Try next endpoint on server errors
                    if response.status_code in (403, 404, 500, 502, 503, 504):
                        last_error = f"HTTP {response.status_code}"
                        continue
                    
                    # Success or client error
                    if request.streaming:
                        body = parse_sse_response(response.text)
                    else:
                        body = response.json() if response.text else {}
                    
                    return AntigravityResponse(
                        success=response.status_code == 200,
                        status_code=response.status_code,
                        headers=dict(response.headers),
                        body=body,
                        error=None if response.status_code == 200 else f"HTTP {response.status_code}",
                    )
                
                except httpx.TimeoutException:
                    last_error = "Request timed out"
                    continue
                except Exception as e:
                    last_error = str(e)
                    continue
        
        # All endpoints failed
        return AntigravityResponse(
            success=False,
            status_code=0,
            headers={},
            body={},
            error=last_error or "All endpoints failed",
        )
    
    async def generate_content(
        self,
        model: str,
        contents: List[Dict[str, Any]],
        access_token: str,
        project_id: Optional[str] = None,
        system_instruction: Optional[str] = None,
        generation_config: Optional[Dict[str, Any]] = None,
        streaming: bool = True,
        header_style: Optional[str] = None,
    ) -> AntigravityResponse:
        """
        Generate content using the Antigravity API.
        
        Args:
            model: Model name
            contents: Conversation contents
            access_token: OAuth access token
            project_id: Antigravity project ID
            system_instruction: Optional system instruction
            generation_config: Optional generation config
            streaming: Whether to use streaming
            header_style: Optional header style override
            
        Returns:
            AntigravityResponse with generated content
        """
        request = prepare_request(
            model=model,
            contents=contents,
            access_token=access_token,
            project_id=project_id,
            system_instruction=system_instruction,
            generation_config=generation_config,
            streaming=streaming,
            header_style=header_style,
        )
        
        return await self.execute(request)
