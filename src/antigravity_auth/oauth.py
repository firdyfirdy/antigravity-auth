"""
Antigravity OAuth Flow

This module handles the OAuth 2.0 flow with PKCE for Antigravity authentication,
including authorization URL generation, token exchange, and project ID resolution.
"""

import base64
import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode

import httpx

from .constants import (
    ANTIGRAVITY_CLIENT_ID,
    ANTIGRAVITY_CLIENT_SECRET,
    ANTIGRAVITY_HEADERS,
    ANTIGRAVITY_LOAD_ENDPOINTS,
    ANTIGRAVITY_REDIRECT_URI,
    ANTIGRAVITY_SCOPES,
    GOOGLE_AUTH_URL,
    GOOGLE_TOKEN_URL,
    GOOGLE_USERINFO_URL,
)


@dataclass
class PKCEParams:
    """PKCE code verifier and challenge."""
    verifier: str
    challenge: str


@dataclass
class AuthorizationResult:
    """Result of generating an authorization URL."""
    url: str
    verifier: str
    project_id: str


@dataclass
class TokenExchangeResult:
    """Result of exchanging an authorization code for tokens."""
    success: bool
    error: Optional[str] = None
    refresh_token: Optional[str] = None
    access_token: Optional[str] = None
    expires_at: Optional[int] = None
    email: Optional[str] = None
    project_id: Optional[str] = None


def generate_pkce() -> PKCEParams:
    """
    Generate PKCE code verifier and challenge.
    
    The verifier is a random string of 43-128 characters.
    The challenge is the base64url-encoded SHA256 hash of the verifier.
    """
    # Generate a random verifier (43-128 characters)
    verifier = secrets.token_urlsafe(32)  # 43 characters
    
    # Generate the challenge (SHA256 hash of verifier, base64url encoded)
    challenge_bytes = hashlib.sha256(verifier.encode('ascii')).digest()
    challenge = base64.urlsafe_b64encode(challenge_bytes).decode('ascii').rstrip('=')
    
    return PKCEParams(verifier=verifier, challenge=challenge)


def encode_state(verifier: str, project_id: str = "") -> str:
    """
    Encode PKCE verifier and project ID into OAuth state parameter.
    
    Args:
        verifier: PKCE code verifier
        project_id: Optional project ID to pass through OAuth flow
        
    Returns:
        Base64url-encoded JSON string
    """
    payload = {"verifier": verifier, "projectId": project_id}
    json_bytes = json.dumps(payload).encode('utf-8')
    return base64.urlsafe_b64encode(json_bytes).decode('ascii').rstrip('=')


def decode_state(state: str) -> tuple[str, str]:
    """
    Decode OAuth state parameter to extract verifier and project ID.
    
    Args:
        state: Base64url-encoded state string
        
    Returns:
        Tuple of (verifier, project_id)
    """
    # Normalize base64url to base64 and add padding
    normalized = state.replace('-', '+').replace('_', '/')
    padding_needed = (4 - len(normalized) % 4) % 4
    padded = normalized + '=' * padding_needed
    
    json_bytes = base64.b64decode(padded)
    payload = json.loads(json_bytes.decode('utf-8'))
    
    return payload.get('verifier', ''), payload.get('projectId', '')


def build_authorization_url(project_id: str = "") -> AuthorizationResult:
    """
    Build the Google OAuth authorization URL with PKCE.
    
    Args:
        project_id: Optional project ID to pass through the OAuth flow
        
    Returns:
        AuthorizationResult with the URL, verifier, and project ID
    """
    pkce = generate_pkce()
    state = encode_state(pkce.verifier, project_id)
    
    params = {
        "client_id": ANTIGRAVITY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": ANTIGRAVITY_REDIRECT_URI,
        "scope": " ".join(ANTIGRAVITY_SCOPES),
        "code_challenge": pkce.challenge,
        "code_challenge_method": "S256",
        "state": state,
        "access_type": "offline",  # Request refresh token
        "prompt": "consent",  # Force consent screen to get refresh token
    }
    
    url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    
    return AuthorizationResult(
        url=url,
        verifier=pkce.verifier,
        project_id=project_id,
    )


async def fetch_user_email(access_token: str) -> Optional[str]:
    """
    Fetch the user's email address using the access token.
    
    Args:
        access_token: OAuth access token
        
    Returns:
        User's email address or None if failed
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                GOOGLE_USERINFO_URL,
                params={"alt": "json"},
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=30.0,
            )
            
            if response.status_code == 200:
                data = response.json()
                return data.get("email")
        except Exception:
            pass
    
    return None


async def fetch_project_id(access_token: str) -> Optional[str]:
    """
    Fetch the user's Antigravity project ID.
    
    Tries endpoints in order: PROD → DAILY → AUTOPUSH
    
    Args:
        access_token: OAuth access token
        
    Returns:
        Project ID string or None if failed
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": "google-api-nodejs-client/9.15.1",
        "X-Goog-Api-Client": "google-cloud-sdk vscode_cloudshelleditor/0.1",
        "Client-Metadata": ANTIGRAVITY_HEADERS["Client-Metadata"],
    }
    
    body = {
        "metadata": {
            "ideType": "IDE_UNSPECIFIED",
            "platform": "PLATFORM_UNSPECIFIED",
            "pluginType": "GEMINI",
        }
    }
    
    async with httpx.AsyncClient() as client:
        for endpoint in ANTIGRAVITY_LOAD_ENDPOINTS:
            try:
                response = await client.post(
                    f"{endpoint}/v1internal:loadCodeAssist",
                    headers=headers,
                    json=body,
                    timeout=30.0,
                )
                
                if response.status_code == 200:
                    data = response.json()
                    project = data.get("cloudaicompanionProject")
                    
                    if project:
                        # Can be string or object with id field
                        if isinstance(project, str):
                            return project
                        elif isinstance(project, dict):
                            return project.get("id")
            except Exception:
                continue
    
    return None


async def exchange_code_for_tokens(
    code: str,
    state: str,
) -> TokenExchangeResult:
    """
    Exchange an authorization code for access and refresh tokens.
    
    Args:
        code: Authorization code from OAuth callback
        state: State parameter from OAuth callback
        
    Returns:
        TokenExchangeResult with tokens and user info
    """
    try:
        verifier, project_id = decode_state(state)
    except Exception as e:
        return TokenExchangeResult(success=False, error=f"Invalid state: {e}")
    
    if not verifier:
        return TokenExchangeResult(success=False, error="Missing verifier in state")
    
    start_time = int(time.time() * 1000)  # Milliseconds
    
    # Exchange code for tokens
    token_data = {
        "client_id": ANTIGRAVITY_CLIENT_ID,
        "client_secret": ANTIGRAVITY_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": ANTIGRAVITY_REDIRECT_URI,
        "code_verifier": verifier,
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                GOOGLE_TOKEN_URL,
                data=token_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30.0,
            )
            
            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error_description", error_data.get("error", "Unknown error"))
                return TokenExchangeResult(success=False, error=f"Token exchange failed: {error_msg}")
            
            tokens = response.json()
            
        except Exception as e:
            return TokenExchangeResult(success=False, error=f"Token exchange request failed: {e}")
    
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    expires_in = tokens.get("expires_in", 3600)
    
    if not access_token or not refresh_token:
        return TokenExchangeResult(success=False, error="Missing tokens in response")
    
    # Calculate expiry timestamp
    expires_at = start_time + (expires_in * 1000)
    
    # Fetch user email
    email = await fetch_user_email(access_token)
    
    # Resolve project ID if not provided
    if not project_id:
        project_id = await fetch_project_id(access_token)
    
    # Format refresh token with project ID: "refresh_token|project_id"
    stored_refresh = f"{refresh_token}|{project_id or ''}"
    
    return TokenExchangeResult(
        success=True,
        refresh_token=stored_refresh,
        access_token=access_token,
        expires_at=expires_at,
        email=email,
        project_id=project_id,
    )
