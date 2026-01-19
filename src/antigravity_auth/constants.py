"""
Antigravity Authentication Constants

This module contains all the OAuth and API constants required for Antigravity
authentication, ported from the TypeScript implementation.
"""

# =============================================================================
# OAuth Configuration
# =============================================================================

ANTIGRAVITY_CLIENT_ID = "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
ANTIGRAVITY_CLIENT_SECRET = "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"

ANTIGRAVITY_SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/cclog",
    "https://www.googleapis.com/auth/experimentsandconfigs",
]

ANTIGRAVITY_REDIRECT_URI = "http://localhost:51121/oauth-callback"
ANTIGRAVITY_REDIRECT_PORT = 51121

# OAuth endpoints
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v1/userinfo"

# =============================================================================
# API Endpoints
# =============================================================================

ANTIGRAVITY_ENDPOINT_DAILY = "https://daily-cloudcode-pa.sandbox.googleapis.com"
ANTIGRAVITY_ENDPOINT_AUTOPUSH = "https://autopush-cloudcode-pa.sandbox.googleapis.com"
ANTIGRAVITY_ENDPOINT_PROD = "https://cloudcode-pa.googleapis.com"

# Endpoint fallback order for API requests
ANTIGRAVITY_ENDPOINT_FALLBACKS = [
    ANTIGRAVITY_ENDPOINT_DAILY,
    ANTIGRAVITY_ENDPOINT_AUTOPUSH,
    ANTIGRAVITY_ENDPOINT_PROD,
]

# Endpoint order for project ID resolution (prefer prod first)
ANTIGRAVITY_LOAD_ENDPOINTS = [
    ANTIGRAVITY_ENDPOINT_PROD,
    ANTIGRAVITY_ENDPOINT_DAILY,
    ANTIGRAVITY_ENDPOINT_AUTOPUSH,
]

# Gemini CLI endpoint (for non-:antigravity models)
GEMINI_CLI_ENDPOINT = ANTIGRAVITY_ENDPOINT_PROD

# =============================================================================
# Request Headers
# =============================================================================

# Headers for Antigravity quota (models with :antigravity suffix)
ANTIGRAVITY_HEADERS = {
    "User-Agent": "antigravity/1.11.5 windows/amd64",
    "X-Goog-Api-Client": "google-cloud-sdk vscode_cloudshelleditor/0.1",
    "Client-Metadata": '{"ideType":"IDE_UNSPECIFIED","platform":"PLATFORM_UNSPECIFIED","pluginType":"GEMINI"}',
}

# Headers for Gemini CLI quota (default models)
GEMINI_CLI_HEADERS = {
    "User-Agent": "google-api-nodejs-client/9.15.1",
    "X-Goog-Api-Client": "gl-node/22.17.0",
    "Client-Metadata": "ideType=IDE_UNSPECIFIED,platform=PLATFORM_UNSPECIFIED,pluginType=GEMINI",
}

# =============================================================================
# Default Values
# =============================================================================

# Default project ID when resolution fails
ANTIGRAVITY_DEFAULT_PROJECT_ID = "rising-fact-p41fc"

# Default model for requests
DEFAULT_MODEL = "gemini-3-pro"

# Token expiry buffer (refresh token 1 minute before expiry)
ACCESS_TOKEN_EXPIRY_BUFFER_MS = 60 * 1000  # 1 minute

# =============================================================================
# Rate Limiting
# =============================================================================

# Rate limit deduplication window (concurrent 429s within this window are deduplicated)
RATE_LIMIT_DEDUP_WINDOW_MS = 2000  # 2 seconds

# Reset consecutive counter after this period of no 429s
RATE_LIMIT_STATE_RESET_MS = 120_000  # 2 minutes

# Short retry threshold (wait and retry same account if below this)
SHORT_RETRY_THRESHOLD_MS = 5000  # 5 seconds

# Capacity backoff tiers
CAPACITY_BACKOFF_TIERS_MS = [5000, 10000, 20000, 30000, 60000]

# Maximum consecutive failures before account cooldown
MAX_CONSECUTIVE_FAILURES = 5

# Cooldown duration after max failures
FAILURE_COOLDOWN_MS = 30_000  # 30 seconds

# Reset failure count after this period of no failures
FAILURE_STATE_RESET_MS = 120_000  # 2 minutes

# =============================================================================
# Provider ID
# =============================================================================

ANTIGRAVITY_PROVIDER_ID = "antigravity"

# =============================================================================
# Header Styles
# =============================================================================

HEADER_STYLE_ANTIGRAVITY = "antigravity"
HEADER_STYLE_GEMINI_CLI = "gemini-cli"

# =============================================================================
# Model Families
# =============================================================================

MODEL_FAMILY_GEMINI = "gemini"
MODEL_FAMILY_CLAUDE = "claude"
MODEL_FAMILY_IMAGE = "image"

# =============================================================================
# Antigravity System Instruction (Required for API compatibility)
# =============================================================================

ANTIGRAVITY_SYSTEM_INSTRUCTION = """<identity>
You are Antigravity, a powerful agentic AI coding assistant designed by the Google DeepMind team working on Advanced Agentic Coding.
You are pair programming with a USER to solve their coding task. The task may require creating a new codebase, modifying or debugging an existing codebase, or simply answering a question.
The USER will send you requests, which you must always prioritize addressing. Along with each USER request, we will attach additional metadata about their current state, such as what files they have open and where their cursor is.
This information may or may not be relevant to the coding task, it is up for you to decide.
</identity>

<tool_calling>
Call tools as you normally would. The following list provides additional guidance to help you avoid errors:
  - **Absolute paths only**. When using tools that accept file path arguments, ALWAYS use the absolute file path.
</tool_calling>

<communication_style>
- **Formatting**. Format your responses in github-style markdown to make your responses easier for the USER to parse.
- **Proactiveness**. As an agent, you are allowed to be proactive, but only in the course of completing the user's task.
- **Helpfulness**. Respond like a helpful software engineer who is explaining your work to a friendly collaborator on the project.
- **Ask for clarification**. If you are unsure about the USER's intent, always ask for clarification rather than making assumptions.
</communication_style>"""

