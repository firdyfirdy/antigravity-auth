"""
Antigravity Token Management

This module handles token parsing, expiry checking, and refresh operations.
"""

import time
from dataclasses import dataclass
from typing import Optional

import httpx

from .constants import (
    ACCESS_TOKEN_EXPIRY_BUFFER_MS,
    ANTIGRAVITY_CLIENT_ID,
    ANTIGRAVITY_CLIENT_SECRET,
    GOOGLE_TOKEN_URL,
)


@dataclass
class RefreshParts:
    """Parsed components of a stored refresh token."""
    refresh_token: str
    project_id: Optional[str] = None
    managed_project_id: Optional[str] = None


@dataclass
class AuthDetails:
    """OAuth authentication details."""
    refresh: str
    access: str
    expires: int  # Expiry timestamp in milliseconds
    email: Optional[str] = None


class TokenRefreshError(Exception):
    """Exception raised when token refresh fails."""
    
    def __init__(self, message: str, code: Optional[str] = None):
        super().__init__(message)
        self.code = code


def parse_refresh_parts(refresh: str) -> RefreshParts:
    """
    Parse a stored refresh token into its components.
    
    Format: "refresh_token|project_id|managed_project_id"
    
    Args:
        refresh: The stored refresh token string
        
    Returns:
        RefreshParts with extracted components
    """
    parts = refresh.split("|")
    
    return RefreshParts(
        refresh_token=parts[0] if len(parts) > 0 else "",
        project_id=parts[1] if len(parts) > 1 and parts[1] else None,
        managed_project_id=parts[2] if len(parts) > 2 and parts[2] else None,
    )


def format_refresh_parts(parts: RefreshParts) -> str:
    """
    Format refresh parts back into a stored refresh token string.
    
    Args:
        parts: RefreshParts to format
        
    Returns:
        Formatted refresh token string
    """
    base = f"{parts.refresh_token}|{parts.project_id or ''}"
    if parts.managed_project_id:
        return f"{base}|{parts.managed_project_id}"
    return base


def is_token_expired(auth: AuthDetails) -> bool:
    """
    Check if an access token is expired or about to expire.
    
    Args:
        auth: AuthDetails containing the token and expiry
        
    Returns:
        True if the token is expired or will expire within the buffer period
    """
    if not auth.access or not auth.expires:
        return True
    
    current_time = int(time.time() * 1000)  # Current time in milliseconds
    return auth.expires <= current_time + ACCESS_TOKEN_EXPIRY_BUFFER_MS


def calculate_token_expiry(request_time_ms: int, expires_in_seconds: int) -> int:
    """
    Calculate the token expiry timestamp.
    
    Args:
        request_time_ms: Request start time in milliseconds
        expires_in_seconds: Token lifetime in seconds
        
    Returns:
        Expiry timestamp in milliseconds
    """
    if expires_in_seconds <= 0:
        return request_time_ms
    return request_time_ms + (expires_in_seconds * 1000)


async def refresh_access_token(auth: AuthDetails) -> Optional[AuthDetails]:
    """
    Refresh an access token using the refresh token.
    
    Args:
        auth: Current AuthDetails with refresh token
        
    Returns:
        Updated AuthDetails with new access token, or None if refresh failed
        
    Raises:
        TokenRefreshError: If the refresh token is invalid (revoked)
    """
    parts = parse_refresh_parts(auth.refresh)
    
    if not parts.refresh_token:
        return None
    
    start_time = int(time.time() * 1000)
    
    refresh_data = {
        "grant_type": "refresh_token",
        "refresh_token": parts.refresh_token,
        "client_id": ANTIGRAVITY_CLIENT_ID,
        "client_secret": ANTIGRAVITY_CLIENT_SECRET,
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                GOOGLE_TOKEN_URL,
                data=refresh_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30.0,
            )
            
            if response.status_code != 200:
                error_data = response.json()
                error_code = error_data.get("error", "unknown_error")
                error_desc = error_data.get("error_description", "Unknown error")
                
                # Check for revoked token
                if error_code == "invalid_grant":
                    raise TokenRefreshError(
                        f"Refresh token is invalid or revoked: {error_desc}",
                        code="invalid_grant",
                    )
                
                return None
            
            tokens = response.json()
            
        except TokenRefreshError:
            raise
        except Exception:
            return None
    
    access_token = tokens.get("access_token")
    expires_in = tokens.get("expires_in", 3600)
    
    # Token rotation: new refresh token may be provided
    new_refresh_token = tokens.get("refresh_token", parts.refresh_token)
    
    if not access_token:
        return None
    
    # Update refresh parts with potentially new refresh token
    new_parts = RefreshParts(
        refresh_token=new_refresh_token,
        project_id=parts.project_id,
        managed_project_id=parts.managed_project_id,
    )
    
    return AuthDetails(
        refresh=format_refresh_parts(new_parts),
        access=access_token,
        expires=calculate_token_expiry(start_time, expires_in),
        email=auth.email,
    )
