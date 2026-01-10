"""
Antigravity Python Authentication Library

A Python port of the opencode-antigravity-auth TypeScript library.
Provides cookie-based authentication for Google Gemini and Claude models
via the Antigravity API.
"""

from .service import (
    AntigravityService,
    AntigravityError,
    NoAccountsError,
    AllAccountsRateLimitedError,
    TokenRefreshFailedError,
)
from .oauth import (
    build_authorization_url,
    exchange_code_for_tokens,
)
from .storage import (
    load_accounts,
    add_or_update_account,
    remove_account_by_email,
    set_active_account,
    clear_accounts,
    get_storage_path,
)
from .token import (
    AuthDetails,
    refresh_access_token,
)


__version__ = "0.1.0"

__all__ = [
    # Main service
    "AntigravityService",
    
    # Exceptions
    "AntigravityError",
    "NoAccountsError", 
    "AllAccountsRateLimitedError",
    "TokenRefreshFailedError",
    
    # OAuth
    "build_authorization_url",
    "exchange_code_for_tokens",
    
    # Storage
    "load_accounts",
    "add_or_update_account",
    "remove_account_by_email",
    "set_active_account",
    "clear_accounts",
    "get_storage_path",
    
    # Token
    "AuthDetails",
    "refresh_access_token",
]
