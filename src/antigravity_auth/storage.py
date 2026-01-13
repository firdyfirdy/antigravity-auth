"""
Antigravity Account Storage

This module handles persistent storage of multiple Antigravity accounts,
including file locking, versioning, and deduplication.
"""

import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from filelock import FileLock, Timeout


# Storage version for migration support
STORAGE_VERSION = 3


@dataclass
class RateLimitResetTimes:
    """Rate limit reset times for different quotas."""
    claude: Optional[int] = None
    gemini_antigravity: Optional[int] = None
    gemini_cli: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Optional[int]]:
        return {
            "claude": self.claude,
            "gemini-antigravity": self.gemini_antigravity,
            "gemini-cli": self.gemini_cli,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RateLimitResetTimes":
        return cls(
            claude=data.get("claude"),
            gemini_antigravity=data.get("gemini-antigravity"),
            gemini_cli=data.get("gemini-cli"),
        )


@dataclass
class AccountMetadata:
    """Metadata for a single Antigravity account."""
    refresh_token: str
    email: Optional[str] = None
    project_id: Optional[str] = None
    managed_project_id: Optional[str] = None
    added_at: int = field(default_factory=lambda: int(time.time() * 1000))
    last_used: int = field(default_factory=lambda: int(time.time() * 1000))
    last_switch_reason: Optional[str] = None  # "rate-limit", "initial", "rotation"
    rate_limit_reset_times: RateLimitResetTimes = field(default_factory=RateLimitResetTimes)
    cooling_down_until: Optional[int] = None
    cooldown_reason: Optional[str] = None  # "auth-failure", "network-error", "project-error"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "refreshToken": self.refresh_token,
            "email": self.email,
            "projectId": self.project_id,
            "managedProjectId": self.managed_project_id,
            "addedAt": self.added_at,
            "lastUsed": self.last_used,
            "lastSwitchReason": self.last_switch_reason,
            "rateLimitResetTimes": self.rate_limit_reset_times.to_dict(),
            "coolingDownUntil": self.cooling_down_until,
            "cooldownReason": self.cooldown_reason,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AccountMetadata":
        rate_limits = data.get("rateLimitResetTimes", {})
        return cls(
            refresh_token=data.get("refreshToken", ""),
            email=data.get("email"),
            project_id=data.get("projectId"),
            managed_project_id=data.get("managedProjectId"),
            added_at=data.get("addedAt", int(time.time() * 1000)),
            last_used=data.get("lastUsed", int(time.time() * 1000)),
            last_switch_reason=data.get("lastSwitchReason"),
            rate_limit_reset_times=RateLimitResetTimes.from_dict(rate_limits) if rate_limits else RateLimitResetTimes(),
            cooling_down_until=data.get("coolingDownUntil"),
            cooldown_reason=data.get("cooldownReason"),
        )


@dataclass
class ActiveIndexByFamily:
    """Track active account index per model family."""
    claude: int = 0
    gemini: int = 0
    
    def to_dict(self) -> Dict[str, int]:
        return {"claude": self.claude, "gemini": self.gemini}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActiveIndexByFamily":
        return cls(
            claude=data.get("claude", 0),
            gemini=data.get("gemini", 0),
        )


@dataclass
class AccountStorage:
    """Container for all stored accounts."""
    version: int = STORAGE_VERSION
    accounts: List[AccountMetadata] = field(default_factory=list)
    active_index: int = 0
    active_index_by_family: ActiveIndexByFamily = field(default_factory=ActiveIndexByFamily)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "accounts": [acc.to_dict() for acc in self.accounts],
            "activeIndex": self.active_index,
            "activeIndexByFamily": self.active_index_by_family.to_dict(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AccountStorage":
        accounts = [AccountMetadata.from_dict(acc) for acc in data.get("accounts", [])]
        active_by_family = data.get("activeIndexByFamily", {})
        return cls(
            version=data.get("version", STORAGE_VERSION),
            accounts=accounts,
            active_index=data.get("activeIndex", 0),
            active_index_by_family=ActiveIndexByFamily.from_dict(active_by_family) if active_by_family else ActiveIndexByFamily(),
        )


def get_config_dir() -> Path:
    """
    Get the configuration directory for storing accounts.
    
    Returns:
        Path to the config directory
    """
    if env_dir := os.environ.get("ANTIGRAVITY_STORAGE_DIR"):
        return Path(env_dir)

    if sys.platform == "win32":
        app_data = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
        return Path(app_data) / "antigravity_auth"
    else:
        xdg_config = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        return Path(xdg_config) / "antigravity_auth"


def get_storage_path(path: Optional[str] = None) -> Path:
    """
    Get the path to the accounts storage file.
    
    Args:
        path: Optional custom path to the storage file
        
    Returns:
        Path to the accounts JSON file
    """
    if path:
        return Path(path)
    
    if env_path := os.environ.get("ANTIGRAVITY_STORAGE_PATH"):
        return Path(env_path)
        
    return get_config_dir() / "accounts.json"


def get_lock_path(storage_path: Path) -> Path:
    """
    Get the path to the lock file based on storage path.
    
    Args:
        storage_path: Path to the storage file
        
    Returns:
        Path to the lock file
    """
    # If using default config dir, keep compatible lock name
    config_dir = get_config_dir()
    if storage_path.parent == config_dir and storage_path.name == "accounts.json":
        return config_dir / "antigravity-accounts.lock"
    
    # Otherwise use a derived name
    return storage_path.parent / f"{storage_path.name}.lock"


def ensure_config_dir(storage_path: Path) -> None:
    """
    Ensure the configuration directory exists.
    
    Args:
        storage_path: Path to the storage file
    """
    storage_path.parent.mkdir(parents=True, exist_ok=True)


def load_accounts_unsafe(storage_path_str: Optional[str] = None) -> Optional[AccountStorage]:
    """
    Load accounts from storage without file locking.
    
    Args:
        storage_path_str: Optional custom storage path
        
    Returns:
        AccountStorage or None if file doesn't exist or is invalid
    """
    storage_path = get_storage_path(storage_path_str)
    
    if not storage_path.exists():
        return None
    
    try:
        with open(storage_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return AccountStorage.from_dict(data)
    except Exception:
        return None


def load_accounts(storage_path_str: Optional[str] = None) -> Optional[AccountStorage]:
    """
    Load accounts from storage with file locking.
    
    Args:
        storage_path_str: Optional custom storage path
        
    Returns:
        AccountStorage or None if file doesn't exist or is invalid
    """
    storage_path = get_storage_path(storage_path_str)
    ensure_config_dir(storage_path)
    
    lock_path = get_lock_path(storage_path)
    lock = FileLock(str(lock_path), timeout=10)
    
    try:
        with lock:
            return load_accounts_unsafe(storage_path_str)
    except Timeout:
        # If we can't acquire the lock, try reading anyway
        return load_accounts_unsafe(storage_path_str)


def save_accounts(storage: AccountStorage, storage_path_str: Optional[str] = None) -> None:
    """
    Save accounts to storage with file locking and atomic write.
    
    Args:
        storage: AccountStorage to save
        storage_path_str: Optional custom storage path
    """
    storage_path = get_storage_path(storage_path_str)
    ensure_config_dir(storage_path)
    
    lock_path = get_lock_path(storage_path)
    lock = FileLock(str(lock_path), timeout=10)
    
    try:
        with lock:
            # Atomic write via temp file
            import secrets
            temp_path = storage_path.with_suffix(f".{secrets.token_hex(6)}.tmp")
            
            try:
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(storage.to_dict(), f, indent=2)
                
                # Atomic rename (on Windows, need to remove target first)
                if sys.platform == "win32" and storage_path.exists():
                    storage_path.unlink()
                temp_path.rename(storage_path)
            finally:
                # Clean up temp file if it still exists
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except Exception:
                        pass
    except Timeout:
        # If we can't acquire the lock, write directly
        with open(storage_path, "w", encoding="utf-8") as f:
            json.dump(storage.to_dict(), f, indent=2)


def clear_accounts(storage_path_str: Optional[str] = None) -> None:
    """
    Remove all stored accounts.
    
    Args:
        storage_path_str: Optional custom storage path
    """
    storage_path = get_storage_path(storage_path_str)
    lock_path = get_lock_path(storage_path)
    
    if storage_path.exists():
        try:
            lock = FileLock(str(lock_path), timeout=10)
            with lock:
                storage_path.unlink()
        except Exception:
            try:
                storage_path.unlink()
            except Exception:
                pass


def deduplicate_accounts_by_email(accounts: List[AccountMetadata]) -> List[AccountMetadata]:
    """
    Deduplicate accounts by email, keeping the newest one.
    
    Accounts without email are preserved as-is.
    
    Args:
        accounts: List of accounts to deduplicate
        
    Returns:
        Deduplicated list of accounts
    """
    by_email: Dict[str, AccountMetadata] = {}
    no_email: List[AccountMetadata] = []
    
    for account in accounts:
        if not account.email:
            no_email.append(account)
            continue
        
        existing = by_email.get(account.email)
        if existing is None:
            by_email[account.email] = account
        else:
            # Keep the one with highest last_used, then added_at
            if account.last_used > existing.last_used:
                by_email[account.email] = account
            elif account.last_used == existing.last_used and account.added_at > existing.added_at:
                by_email[account.email] = account
    
    return list(by_email.values()) + no_email


def add_or_update_account(
    email: Optional[str],
    refresh_token: str,
    project_id: Optional[str] = None,
    managed_project_id: Optional[str] = None,
    storage_path: Optional[str] = None,
) -> AccountStorage:
    """
    Add a new account or update an existing one.
    
    If an account with the same email exists, update it.
    Otherwise, add a new account.
    
    Args:
        email: User's email address
        refresh_token: OAuth refresh token
        project_id: Antigravity project ID
        managed_project_id: Managed project ID
        storage_path: Optional custom storage path
        
    Returns:
        Updated AccountStorage
    """
    now = int(time.time() * 1000)
    storage = load_accounts(storage_path) or AccountStorage()
    
    # Check if account with same email exists
    existing_index = None
    if email:
        for i, account in enumerate(storage.accounts):
            if account.email == email:
                existing_index = i
                break
    
    if existing_index is not None:
        # Update existing account
        storage.accounts[existing_index].refresh_token = refresh_token
        storage.accounts[existing_index].project_id = project_id or storage.accounts[existing_index].project_id
        storage.accounts[existing_index].managed_project_id = managed_project_id or storage.accounts[existing_index].managed_project_id
        storage.accounts[existing_index].last_used = now
    else:
        # Add new account
        new_account = AccountMetadata(
            refresh_token=refresh_token,
            email=email,
            project_id=project_id,
            managed_project_id=managed_project_id,
            added_at=now,
            last_used=now,
        )
        storage.accounts.append(new_account)
    
    # Deduplicate and save
    storage.accounts = deduplicate_accounts_by_email(storage.accounts)
    
    # Ensure active index is valid
    if storage.active_index >= len(storage.accounts):
        storage.active_index = 0
    
    save_accounts(storage, storage_path)
    return storage


def remove_account_by_email(email: str, storage_path: Optional[str] = None) -> bool:
    """
    Remove an account by email address.
    
    Args:
        email: Email of account to remove
        storage_path: Optional custom storage path
        
    Returns:
        True if account was removed, False if not found
    """
    storage = load_accounts(storage_path)
    if not storage:
        return False
    
    original_count = len(storage.accounts)
    storage.accounts = [acc for acc in storage.accounts if acc.email != email]
    
    if len(storage.accounts) == original_count:
        return False
    
    # Ensure active index is valid
    if storage.active_index >= len(storage.accounts):
        storage.active_index = max(0, len(storage.accounts) - 1)
    
    save_accounts(storage, storage_path)
    return True


def set_active_account(index: int, storage_path: Optional[str] = None) -> bool:
    """
    Set the active account by index.
    
    Args:
        index: Index of account to make active
        storage_path: Optional custom storage path
        
    Returns:
        True if successful, False if index is invalid
    """
    storage = load_accounts(storage_path)
    if not storage or index < 0 or index >= len(storage.accounts):
        return False
    
    storage.active_index = index
    storage.active_index_by_family.gemini = index
    storage.active_index_by_family.claude = index
    
    save_accounts(storage, storage_path)
    return True
