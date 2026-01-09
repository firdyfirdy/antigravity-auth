"""
Antigravity Account Manager

This module manages a pool of Antigravity accounts, handling selection,
rotation, rate limit tracking, and quota management.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

from .constants import (
    CAPACITY_BACKOFF_TIERS_MS,
    FAILURE_COOLDOWN_MS,
    FAILURE_STATE_RESET_MS,
    HEADER_STYLE_ANTIGRAVITY,
    HEADER_STYLE_GEMINI_CLI,
    MAX_CONSECUTIVE_FAILURES,
    MODEL_FAMILY_CLAUDE,
    MODEL_FAMILY_GEMINI,
    RATE_LIMIT_DEDUP_WINDOW_MS,
    RATE_LIMIT_STATE_RESET_MS,
    SHORT_RETRY_THRESHOLD_MS,
)
from .storage import (
    AccountMetadata,
    AccountStorage,
    RateLimitResetTimes,
    load_accounts,
    save_accounts,
)
from .token import AuthDetails, parse_refresh_parts, format_refresh_parts, RefreshParts


ModelFamily = Literal["gemini", "claude"]
HeaderStyle = Literal["antigravity", "gemini-cli"]
SelectionStrategy = Literal["sticky", "round-robin", "hybrid"]


@dataclass
class ManagedAccount:
    """A managed account with runtime state."""
    index: int
    email: Optional[str]
    refresh_token: str
    project_id: Optional[str]
    managed_project_id: Optional[str]
    added_at: int
    last_used: int
    rate_limit_reset_times: Dict[str, int] = field(default_factory=dict)
    cooling_down_until: Optional[int] = None
    cooldown_reason: Optional[str] = None
    consecutive_failures: int = 0
    
    @classmethod
    def from_metadata(cls, index: int, metadata: AccountMetadata) -> "ManagedAccount":
        rate_limits = {}
        if metadata.rate_limit_reset_times.claude:
            rate_limits["claude"] = metadata.rate_limit_reset_times.claude
        if metadata.rate_limit_reset_times.gemini_antigravity:
            rate_limits["gemini-antigravity"] = metadata.rate_limit_reset_times.gemini_antigravity
        if metadata.rate_limit_reset_times.gemini_cli:
            rate_limits["gemini-cli"] = metadata.rate_limit_reset_times.gemini_cli
        
        return cls(
            index=index,
            email=metadata.email,
            refresh_token=metadata.refresh_token,
            project_id=metadata.project_id,
            managed_project_id=metadata.managed_project_id,
            added_at=metadata.added_at,
            last_used=metadata.last_used,
            rate_limit_reset_times=rate_limits,
            cooling_down_until=metadata.cooling_down_until,
            cooldown_reason=metadata.cooldown_reason,
        )
    
    def to_metadata(self) -> AccountMetadata:
        rate_limits = RateLimitResetTimes(
            claude=self.rate_limit_reset_times.get("claude"),
            gemini_antigravity=self.rate_limit_reset_times.get("gemini-antigravity"),
            gemini_cli=self.rate_limit_reset_times.get("gemini-cli"),
        )
        
        return AccountMetadata(
            refresh_token=self.refresh_token,
            email=self.email,
            project_id=self.project_id,
            managed_project_id=self.managed_project_id,
            added_at=self.added_at,
            last_used=self.last_used,
            rate_limit_reset_times=rate_limits,
            cooling_down_until=self.cooling_down_until,
            cooldown_reason=self.cooldown_reason,
        )


def get_quota_key(family: ModelFamily, header_style: HeaderStyle, model: Optional[str] = None) -> str:
    """
    Get the quota key for rate limit tracking.
    
    Args:
        family: Model family (gemini or claude)
        header_style: Header style (antigravity or gemini-cli)
        model: Optional model name for model-specific tracking
        
    Returns:
        Quota key string
    """
    if family == MODEL_FAMILY_CLAUDE:
        return "claude"
    
    base = "gemini-antigravity" if header_style == HEADER_STYLE_ANTIGRAVITY else "gemini-cli"
    
    # Model-specific tracking for per-model quotas
    if model:
        return f"{base}:{model}"
    
    return base


class AccountManager:
    """
    Manages a pool of Antigravity accounts with selection, rotation,
    and rate limit tracking.
    """
    
    def __init__(self, storage: Optional[AccountStorage] = None):
        """
        Initialize the account manager.
        
        Args:
            storage: Optional pre-loaded storage, otherwise loads from disk
        """
        self._storage = storage or load_accounts() or AccountStorage()
        self._accounts: List[ManagedAccount] = []
        self._active_index_by_family: Dict[str, int] = {
            MODEL_FAMILY_GEMINI: self._storage.active_index_by_family.gemini,
            MODEL_FAMILY_CLAUDE: self._storage.active_index_by_family.claude,
        }
        self._last_toast_shown_at: Dict[int, int] = {}
        self._toast_debounce_ms = 10000  # 10 seconds
        
        # Load accounts from storage
        for i, metadata in enumerate(self._storage.accounts):
            self._accounts.append(ManagedAccount.from_metadata(i, metadata))
    
    @classmethod
    async def load_from_disk(cls, current_auth: Optional[AuthDetails] = None) -> "AccountManager":
        """
        Load account manager from disk, optionally ensuring current auth is included.
        
        Args:
            current_auth: Optional current auth to ensure is in the pool
            
        Returns:
            AccountManager instance
        """
        manager = cls()
        
        # Ensure current auth is in the pool
        if current_auth:
            parts = parse_refresh_parts(current_auth.refresh)
            if parts.refresh_token:
                manager.ensure_account_exists(
                    refresh_token=parts.refresh_token,
                    project_id=parts.project_id,
                    managed_project_id=parts.managed_project_id,
                    email=current_auth.email,
                )
        
        return manager
    
    def get_account_count(self) -> int:
        """Get the number of accounts in the pool."""
        return len(self._accounts)
    
    def get_accounts(self) -> List[ManagedAccount]:
        """Get all managed accounts."""
        return self._accounts.copy()
    
    def ensure_account_exists(
        self,
        refresh_token: str,
        project_id: Optional[str] = None,
        managed_project_id: Optional[str] = None,
        email: Optional[str] = None,
    ) -> ManagedAccount:
        """
        Ensure an account exists in the pool, adding it if not.
        
        Args:
            refresh_token: The refresh token
            project_id: Optional project ID
            managed_project_id: Optional managed project ID
            email: Optional email address
            
        Returns:
            The existing or newly created ManagedAccount
        """
        # Check if already exists by refresh token
        for account in self._accounts:
            if account.refresh_token == refresh_token:
                return account
        
        # Check by email if provided
        if email:
            for account in self._accounts:
                if account.email == email:
                    # Update with new refresh token
                    account.refresh_token = refresh_token
                    account.project_id = project_id or account.project_id
                    account.managed_project_id = managed_project_id or account.managed_project_id
                    return account
        
        # Add new account
        now = int(time.time() * 1000)
        new_account = ManagedAccount(
            index=len(self._accounts),
            email=email,
            refresh_token=refresh_token,
            project_id=project_id,
            managed_project_id=managed_project_id,
            added_at=now,
            last_used=now,
        )
        self._accounts.append(new_account)
        return new_account
    
    def is_rate_limited(self, account: ManagedAccount, family: ModelFamily, model: Optional[str] = None) -> bool:
        """
        Check if an account is rate-limited for a family.
        
        Args:
            account: Account to check
            family: Model family
            model: Optional model name
            
        Returns:
            True if rate-limited
        """
        now = int(time.time() * 1000)
        
        # Check cooldown
        if account.cooling_down_until and account.cooling_down_until > now:
            return True
        
        # Check family-level rate limits
        if family == MODEL_FAMILY_CLAUDE:
            reset_time = account.rate_limit_reset_times.get("claude", 0)
            return reset_time > now
        
        # For Gemini, check both quota types
        antigravity_key = get_quota_key(family, HEADER_STYLE_ANTIGRAVITY, model)
        cli_key = get_quota_key(family, HEADER_STYLE_GEMINI_CLI, model)
        
        antigravity_reset = account.rate_limit_reset_times.get(antigravity_key, 0)
        cli_reset = account.rate_limit_reset_times.get(cli_key, 0)
        
        # Rate-limited only if BOTH quotas are exhausted
        return antigravity_reset > now and cli_reset > now
    
    def is_rate_limited_for_header_style(
        self,
        account: ManagedAccount,
        family: ModelFamily,
        header_style: HeaderStyle,
        model: Optional[str] = None,
    ) -> bool:
        """
        Check if an account is rate-limited for a specific header style.
        
        Args:
            account: Account to check
            family: Model family
            header_style: Header style to check
            model: Optional model name
            
        Returns:
            True if rate-limited for this header style
        """
        now = int(time.time() * 1000)
        
        if account.cooling_down_until and account.cooling_down_until > now:
            return True
        
        quota_key = get_quota_key(family, header_style, model)
        reset_time = account.rate_limit_reset_times.get(quota_key, 0)
        return reset_time > now
    
    def get_available_header_style(
        self,
        account: ManagedAccount,
        family: ModelFamily,
        model: Optional[str] = None,
    ) -> Optional[HeaderStyle]:
        """
        Get an available header style for an account.
        
        Prefers antigravity, falls back to gemini-cli.
        
        Args:
            account: Account to check
            family: Model family
            model: Optional model name
            
        Returns:
            Available header style or None if all exhausted
        """
        if family == MODEL_FAMILY_CLAUDE:
            if not self.is_rate_limited_for_header_style(account, family, HEADER_STYLE_ANTIGRAVITY, model):
                return HEADER_STYLE_ANTIGRAVITY
            return None
        
        # For Gemini, prefer antigravity
        if not self.is_rate_limited_for_header_style(account, family, HEADER_STYLE_ANTIGRAVITY, model):
            return HEADER_STYLE_ANTIGRAVITY
        
        if not self.is_rate_limited_for_header_style(account, family, HEADER_STYLE_GEMINI_CLI, model):
            return HEADER_STYLE_GEMINI_CLI
        
        return None
    
    def get_current_account_for_family(self, family: ModelFamily) -> Optional[ManagedAccount]:
        """
        Get the current active account for a model family.
        
        Args:
            family: Model family
            
        Returns:
            Current account or None
        """
        if not self._accounts:
            return None
        
        index = self._active_index_by_family.get(family, 0)
        if 0 <= index < len(self._accounts):
            return self._accounts[index]
        
        return self._accounts[0] if self._accounts else None
    
    def get_next_for_family(
        self,
        family: ModelFamily,
        model: Optional[str] = None,
    ) -> Optional[ManagedAccount]:
        """
        Get the next available account for a model family.
        
        Args:
            family: Model family
            model: Optional model name
            
        Returns:
            Next available account or None if all rate-limited
        """
        if not self._accounts:
            return None
        
        current_index = self._active_index_by_family.get(family, 0)
        
        # Try each account starting from current
        for offset in range(len(self._accounts)):
            index = (current_index + offset) % len(self._accounts)
            account = self._accounts[index]
            
            if not self.is_rate_limited(account, family, model):
                self._active_index_by_family[family] = index
                account.last_used = int(time.time() * 1000)
                return account
        
        return None
    
    def get_current_or_next_for_family(
        self,
        family: ModelFamily,
        model: Optional[str] = None,
        strategy: SelectionStrategy = "sticky",
        header_style: HeaderStyle = HEADER_STYLE_ANTIGRAVITY,
        pid_offset_enabled: bool = False,
    ) -> Optional[ManagedAccount]:
        """
        Get the current account or rotate to the next available one.
        
        Args:
            family: Model family
            model: Optional model name
            strategy: Selection strategy
            header_style: Preferred header style
            pid_offset_enabled: Whether to use PID-based offset for initial selection
            
        Returns:
            Available account or None if all rate-limited
        """
        current = self.get_current_account_for_family(family)
        
        if current and not self.is_rate_limited_for_header_style(current, family, header_style, model):
            current.last_used = int(time.time() * 1000)
            return current
        
        return self.get_next_for_family(family, model)
    
    def mark_rate_limited(
        self,
        account: ManagedAccount,
        retry_after_ms: int,
        family: ModelFamily,
        header_style: HeaderStyle,
        model: Optional[str] = None,
    ) -> None:
        """
        Mark an account as rate-limited for a specific quota.
        
        Args:
            account: Account to mark
            retry_after_ms: Time until rate limit resets
            family: Model family
            header_style: Header style that was used
            model: Optional model name
        """
        quota_key = get_quota_key(family, header_style, model)
        reset_time = int(time.time() * 1000) + retry_after_ms
        account.rate_limit_reset_times[quota_key] = reset_time
    
    def mark_account_cooling_down(
        self,
        account: ManagedAccount,
        cooldown_ms: int,
        reason: str,
    ) -> None:
        """
        Put an account on cooldown.
        
        Args:
            account: Account to cool down
            cooldown_ms: Cooldown duration
            reason: Reason for cooldown
        """
        account.cooling_down_until = int(time.time() * 1000) + cooldown_ms
        account.cooldown_reason = reason
    
    def get_min_wait_time_for_family(
        self,
        family: ModelFamily,
        model: Optional[str] = None,
    ) -> int:
        """
        Get the minimum wait time until any account is available.
        
        Args:
            family: Model family
            model: Optional model name
            
        Returns:
            Wait time in milliseconds (0 if an account is available)
        """
        now = int(time.time() * 1000)
        min_wait = float("inf")
        
        for account in self._accounts:
            if not self.is_rate_limited(account, family, model):
                return 0
            
            # Find the soonest reset time
            if account.cooling_down_until:
                wait = account.cooling_down_until - now
                min_wait = min(min_wait, max(0, wait))
            
            for key, reset_time in account.rate_limit_reset_times.items():
                if family == MODEL_FAMILY_CLAUDE and not key.startswith("claude"):
                    continue
                if family == MODEL_FAMILY_GEMINI and key.startswith("claude"):
                    continue
                
                wait = reset_time - now
                min_wait = min(min_wait, max(0, wait))
        
        return int(min_wait) if min_wait != float("inf") else 60000
    
    def remove_account(self, account: ManagedAccount) -> bool:
        """
        Remove an account from the pool.
        
        Args:
            account: Account to remove
            
        Returns:
            True if removed
        """
        try:
            self._accounts.remove(account)
            
            # Reindex remaining accounts
            for i, acc in enumerate(self._accounts):
                acc.index = i
            
            # Fix active indices
            for family in [MODEL_FAMILY_GEMINI, MODEL_FAMILY_CLAUDE]:
                if self._active_index_by_family.get(family, 0) >= len(self._accounts):
                    self._active_index_by_family[family] = max(0, len(self._accounts) - 1)
            
            return True
        except ValueError:
            return False
    
    def update_from_auth(self, account: ManagedAccount, auth: AuthDetails) -> None:
        """
        Update an account from refreshed auth details.
        
        Args:
            account: Account to update
            auth: New auth details
        """
        parts = parse_refresh_parts(auth.refresh)
        account.refresh_token = parts.refresh_token
        if parts.project_id:
            account.project_id = parts.project_id
        if parts.managed_project_id:
            account.managed_project_id = parts.managed_project_id
        if auth.email:
            account.email = auth.email
    
    def to_auth_details(self, account: ManagedAccount) -> AuthDetails:
        """
        Convert a managed account to auth details.
        
        Args:
            account: Account to convert
            
        Returns:
            AuthDetails for the account
        """
        parts = RefreshParts(
            refresh_token=account.refresh_token,
            project_id=account.project_id,
            managed_project_id=account.managed_project_id,
        )
        
        return AuthDetails(
            refresh=format_refresh_parts(parts),
            access="",  # Needs to be refreshed
            expires=0,
            email=account.email,
        )
    
    def should_show_account_toast(self, account_index: int) -> bool:
        """
        Check if we should show a toast for switching to an account.
        
        Args:
            account_index: Index of account being switched to
            
        Returns:
            True if toast should be shown
        """
        now = int(time.time() * 1000)
        last_shown = self._last_toast_shown_at.get(account_index, 0)
        return (now - last_shown) > self._toast_debounce_ms
    
    def mark_toast_shown(self, account_index: int) -> None:
        """Mark that a toast was shown for an account."""
        self._last_toast_shown_at[account_index] = int(time.time() * 1000)
    
    async def save_to_disk(self) -> None:
        """Save current account state to disk."""
        storage = AccountStorage(
            accounts=[acc.to_metadata() for acc in self._accounts],
            active_index=self._active_index_by_family.get(MODEL_FAMILY_GEMINI, 0),
        )
        storage.active_index_by_family.gemini = self._active_index_by_family.get(MODEL_FAMILY_GEMINI, 0)
        storage.active_index_by_family.claude = self._active_index_by_family.get(MODEL_FAMILY_CLAUDE, 0)
        
        save_accounts(storage)
    
    def get_accounts_snapshot(self) -> List[Dict]:
        """Get a snapshot of all accounts for debugging."""
        return [
            {
                "index": acc.index,
                "email": acc.email,
                "rateLimitResetTimes": acc.rate_limit_reset_times,
                "coolingDownUntil": acc.cooling_down_until,
            }
            for acc in self._accounts
        ]
