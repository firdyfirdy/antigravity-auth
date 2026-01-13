"""
Antigravity Service

This is the main service class that provides a high-level interface for
using the Antigravity API with automatic authentication, token refresh,
and multi-account rotation.
"""

import asyncio
import time
from typing import Any, Dict, List, Optional

from .accounts import AccountManager, ManagedAccount, ModelFamily, HeaderStyle
from .client import (
    AntigravityClient,
    AntigravityResponse,
    extract_text_from_response,
    get_header_style_from_model,
    get_model_family,
)
from .constants import (
    ANTIGRAVITY_DEFAULT_PROJECT_ID,
    DEFAULT_MODEL,
    FAILURE_COOLDOWN_MS,
    HEADER_STYLE_ANTIGRAVITY,
    MAX_CONSECUTIVE_FAILURES,
    MODEL_FAMILY_CLAUDE,
    MODEL_FAMILY_GEMINI,
    SHORT_RETRY_THRESHOLD_MS,
)
from .storage import load_accounts
from .token import (
    AuthDetails,
    TokenRefreshError,
    is_token_expired,
    parse_refresh_parts,
    refresh_access_token,
)


class AntigravityError(Exception):
    """Base exception for Antigravity errors."""
    pass


class NoAccountsError(AntigravityError):
    """Raised when no accounts are available."""
    pass


class AllAccountsRateLimitedError(AntigravityError):
    """Raised when all accounts are rate-limited."""
    
    def __init__(self, message: str, wait_time_ms: int):
        super().__init__(message)
        self.wait_time_ms = wait_time_ms


class TokenRefreshFailedError(AntigravityError):
    """Raised when token refresh fails."""
    pass


class AntigravityService:
    """
    Main service for interacting with the Antigravity API.
    
    Handles authentication, token refresh, multi-account management,
    and automatic retry with rate limit handling.
    """
    
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        max_rate_limit_wait_seconds: int = 300,
        quiet_mode: bool = False,
        quota_fallback: bool = True,
    ):
        """
        Initialize the Antigravity service.
        
        Args:
            model: Default model to use
            max_rate_limit_wait_seconds: Maximum time to wait for rate limit reset
            quiet_mode: Suppress status messages
            quota_fallback: Enable quota fallback (antigravity -> gemini-cli)
        """
        self.model = model
        self.max_rate_limit_wait_seconds = max_rate_limit_wait_seconds
        self.quiet_mode = quiet_mode
        self.quota_fallback = quota_fallback
        
        self._client = AntigravityClient()
        self._account_manager: Optional[AccountManager] = None
        self._current_auth: Dict[int, AuthDetails] = {}  # Cache auth by account index
    
    def _ensure_account_manager(self) -> AccountManager:
        """Ensure the account manager is loaded."""
        if self._account_manager is None:
            self._account_manager = AccountManager()
        return self._account_manager
    
    async def _get_auth_for_account(self, account: ManagedAccount) -> Optional[AuthDetails]:
        """
        Get or refresh auth details for an account.
        
        Args:
            account: Account to get auth for
            
        Returns:
            AuthDetails or None if refresh failed
        """
        # Check cache
        cached = self._current_auth.get(account.index)
        if cached and not is_token_expired(cached):
            return cached
        
        # Build auth from account
        parts = parse_refresh_parts(account.refresh_token)
        auth = AuthDetails(
            refresh=account.refresh_token,
            access=cached.access if cached else "",
            expires=cached.expires if cached else 0,
            email=account.email,
        )
        
        # Refresh if expired
        if is_token_expired(auth):
            try:
                refreshed = await refresh_access_token(auth)
                if refreshed:
                    # Update account with potentially new refresh token
                    account.refresh_token = parse_refresh_parts(refreshed.refresh).refresh_token
                    self._current_auth[account.index] = refreshed
                    return refreshed
                return None
            except TokenRefreshError as e:
                if e.code == "invalid_grant":
                    # Token revoked - remove account
                    manager = self._ensure_account_manager()
                    manager.remove_account(account)
                    await manager.save_to_disk()
                    raise TokenRefreshFailedError(f"Token revoked for {account.email}. Please re-login.")
                return None
        
        self._current_auth[account.index] = auth
        return auth
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        generation_config: Optional[Dict[str, Any]] = None,
        max_retries: int = 3,
    ) -> str:
        """
        Generate content using the Antigravity API.
        
        This is the main method for sending prompts and receiving responses.
        Handles authentication, token refresh, and multi-account rotation automatically.
        
        Args:
            prompt: The user prompt
            system_prompt: Optional system instruction
            model: Model to use (defaults to instance model)
            generation_config: Optional generation config
            max_retries: Maximum number of account rotation retries
            
        Returns:
            Generated text response
            
        Raises:
            NoAccountsError: If no accounts are configured
            AllAccountsRateLimitedError: If all accounts are rate-limited
            AntigravityError: For other API errors
        """
        effective_model = model or self.model
        family = get_model_family(effective_model)
        header_style = get_header_style_from_model(effective_model)
        
        manager = self._ensure_account_manager()
        
        if manager.get_account_count() == 0:
            raise NoAccountsError(
                "No Antigravity accounts configured. Run 'antigravity auth login' to add an account."
            )
        
        # Build contents in Gemini format
        contents = [
            {
                "role": "user",
                "parts": [{"text": prompt}]
            }
        ]
        
        retries = 0
        last_error: Optional[str] = None
        
        while retries < max_retries:
            # Get next available account
            account = manager.get_current_or_next_for_family(
                family=family,
                model=effective_model,
                header_style=header_style,
            )
            
            if account is None:
                # All accounts rate-limited
                wait_time = manager.get_min_wait_time_for_family(family, effective_model)
                max_wait_ms = self.max_rate_limit_wait_seconds * 1000
                
                if max_wait_ms > 0 and wait_time > max_wait_ms:
                    raise AllAccountsRateLimitedError(
                        f"All accounts rate-limited. Retry in {wait_time // 1000}s.",
                        wait_time,
                    )
                
                # Wait and retry
                if not self.quiet_mode:
                    print(f"All accounts rate-limited. Waiting {wait_time // 1000}s...")
                await asyncio.sleep(wait_time / 1000)
                continue
            
            # Get auth for this account
            try:
                auth = await self._get_auth_for_account(account)
            except TokenRefreshFailedError:
                retries += 1
                continue
            
            if not auth or not auth.access:
                retries += 1
                last_error = "Failed to get access token"
                continue
            
            # Get project ID
            project_id = account.project_id or ANTIGRAVITY_DEFAULT_PROJECT_ID
            
            # Make the request
            response = await self._client.generate_content(
                model=effective_model,
                contents=contents,
                access_token=auth.access,
                project_id=project_id,
                system_instruction=system_prompt,
                generation_config=generation_config,
                streaming=True,
                header_style=header_style,
            )
            
            # Handle rate limiting
            if response.status_code == 429:
                retry_after_ms = response.retry_after_ms or 60000
                
                if retry_after_ms <= SHORT_RETRY_THRESHOLD_MS:
                    # Short retry - wait and try same account
                    if not self.quiet_mode:
                        print(f"Rate limited. Retrying in {retry_after_ms // 1000}s...")
                    await asyncio.sleep(retry_after_ms / 1000)
                    continue
                
                # Mark account as rate-limited
                manager.mark_rate_limited(
                    account=account,
                    retry_after_ms=retry_after_ms,
                    family=family,
                    header_style=header_style,
                    model=effective_model,
                )
                await manager.save_to_disk()
                
                # Try quota fallback for Gemini
                if self.quota_fallback and family == MODEL_FAMILY_GEMINI:
                    alt_style = manager.get_available_header_style(account, family, effective_model)
                    if alt_style and alt_style != header_style:
                        header_style = alt_style
                        if not self.quiet_mode:
                            print(f"Quota exhausted. Trying {alt_style} quota...")
                        continue
                
                retries += 1
                last_error = f"Rate limited for {retry_after_ms // 1000}s"
                continue
            
            # Handle success
            if response.success:
                account.consecutive_failures = 0
                await manager.save_to_disk()
                return extract_text_from_response(response.body, streaming=True)
            
            # Handle other errors
            last_error = response.error or "Unknown error"
            retries += 1
        
        raise AntigravityError(f"Failed after {max_retries} retries: {last_error}")
    
    async def generate_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        generation_config: Optional[Dict[str, Any]] = None,
    ):
        """
        Generate content with real-time streaming.
        
        This is an async generator that yields text chunks as they are generated
        by the model, enabling true real-time streaming responses.
        
        Args:
            prompt: The user prompt
            system_prompt: Optional system instruction
            model: Model to use (defaults to instance model)
            generation_config: Optional generation config
            
        Yields:
            String chunks of generated text as they arrive
            
        Raises:
            NoAccountsError: If no accounts are configured
            AllAccountsRateLimitedError: If all accounts are rate-limited
            AntigravityError: For other API errors
            
        Example:
            async for chunk in service.generate_stream("Tell me a story"):
                print(chunk, end="", flush=True)
        """
        effective_model = model or self.model
        family = get_model_family(effective_model)
        header_style = get_header_style_from_model(effective_model)
        
        manager = self._ensure_account_manager()
        
        if manager.get_account_count() == 0:
            raise NoAccountsError(
                "No Antigravity accounts configured. Run 'antigravity auth login' to add an account."
            )
        
        # Build contents in Gemini format
        contents = [
            {
                "role": "user",
                "parts": [{"text": prompt}]
            }
        ]
        
        # Get next available account
        account = manager.get_current_or_next_for_family(
            family=family,
            model=effective_model,
            header_style=header_style,
        )
        
        if account is None:
            wait_time = manager.get_min_wait_time_for_family(family, effective_model)
            raise AllAccountsRateLimitedError(
                f"All accounts rate-limited. Retry in {wait_time // 1000}s.",
                wait_time,
            )
        
        # Get auth for this account
        auth = await self._get_auth_for_account(account)
        
        if not auth or not auth.access:
            raise AntigravityError("Failed to get access token")
        
        # Get project ID
        project_id = account.project_id or ANTIGRAVITY_DEFAULT_PROJECT_ID
        
        # Stream the response
        async for event in self._client.generate_content_stream(
            model=effective_model,
            contents=contents,
            access_token=auth.access,
            project_id=project_id,
            system_instruction=system_prompt,
            generation_config=generation_config,
            header_style=header_style,
        ):
            if "text" in event:
                yield event["text"]
            elif "error" in event:
                if event.get("status_code") == 429:
                    retry_after_ms = event.get("retry_after_ms", 60000)
                    manager.mark_rate_limited(
                        account=account,
                        retry_after_ms=retry_after_ms,
                        family=family,
                        header_style=header_style,
                        model=effective_model,
                    )
                    await manager.save_to_disk()
                    raise AllAccountsRateLimitedError(
                        f"Rate limited. Retry in {retry_after_ms // 1000}s.",
                        retry_after_ms,
                    )
                else:
                    raise AntigravityError(event.get("message", "Stream error"))
            elif "done" in event:
                # Stream completed successfully
                account.consecutive_failures = 0
                await manager.save_to_disk()
                return
    
    def generate_sync(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        generation_config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Synchronous wrapper for generate().
        
        Args:
            prompt: The user prompt
            system_prompt: Optional system instruction
            model: Model to use
            generation_config: Optional generation config
            
        Returns:
            Generated text response
        """
        return asyncio.run(
            self.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                model=model,
                generation_config=generation_config,
            )
        )
    
    async def generate_with_history(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        generation_config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Generate content with conversation history.
        
        Args:
            messages: List of messages with 'role' and 'content' keys
            system_prompt: Optional system instruction
            model: Model to use
            generation_config: Optional generation config
            
        Returns:
            Generated text response
        """
        effective_model = model or self.model
        family = get_model_family(effective_model)
        header_style = get_header_style_from_model(effective_model)
        
        manager = self._ensure_account_manager()
        
        if manager.get_account_count() == 0:
            raise NoAccountsError(
                "No Antigravity accounts configured. Run 'antigravity auth login' to add an account."
            )
        
        # Convert to Gemini format
        contents = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            # Map roles
            if role == "assistant":
                role = "model"
            elif role not in ("user", "model"):
                role = "user"
            
            contents.append({
                "role": role,
                "parts": [{"text": content}]
            })
        
        # Get account and make request
        account = manager.get_current_or_next_for_family(family, effective_model, header_style)
        
        if account is None:
            wait_time = manager.get_min_wait_time_for_family(family, effective_model)
            raise AllAccountsRateLimitedError(
                f"All accounts rate-limited. Retry in {wait_time // 1000}s.",
                wait_time,
            )
        
        auth = await self._get_auth_for_account(account)
        if not auth or not auth.access:
            raise AntigravityError("Failed to get access token")
        
        project_id = account.project_id or ANTIGRAVITY_DEFAULT_PROJECT_ID
        
        response = await self._client.generate_content(
            model=effective_model,
            contents=contents,
            access_token=auth.access,
            project_id=project_id,
            system_instruction=system_prompt,
            generation_config=generation_config,
            streaming=True,
            header_style=header_style,
        )
        
        if response.success:
            return extract_text_from_response(response.body, streaming=True)
        
        raise AntigravityError(response.error or "API request failed")
    
    def get_accounts(self) -> List[Dict[str, Any]]:
        """
        Get list of configured accounts.
        
        Returns:
            List of account info dictionaries
        """
        manager = self._ensure_account_manager()
        return [
            {
                "index": acc.index,
                "email": acc.email,
                "project_id": acc.project_id,
                "added_at": acc.added_at,
                "last_used": acc.last_used,
            }
            for acc in manager.get_accounts()
        ]
    
    def get_active_account(self) -> Optional[Dict[str, Any]]:
        """
        Get the currently active account.
        
        Returns:
            Active account info or None
        """
        manager = self._ensure_account_manager()
        account = manager.get_current_account_for_family(MODEL_FAMILY_GEMINI)
        
        if account:
            return {
                "index": account.index,
                "email": account.email,
                "project_id": account.project_id,
            }
        
        return None
