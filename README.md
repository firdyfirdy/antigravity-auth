# Antigravity Auth

A robust Python client for **Antigravity authentication**, enabling access to internal Google Gemini and Anthropic Claude models via the internal Cloud Code API. 

This library is a faithful Python port of the TypeScript [opencode-antigravity-auth](https://github.com/NoeFabris/opencode-antigravity-auth) library, designed to provide the same powerful capabilities to Python-based tools and agents.

## 🌟 Features

- **🔐 OAuth 2.0 with PKCE**: Secure, browser-based authentication flow.
- **🔄 Multi-Account Support**: Manage multiple Google accounts with automatic rotation.
- **⚡ Automatic Token Refresh**: Handles short-lived access tokens transparently.
- **🛡️ Rate Limit Handling**: Smart backoff and account switching on 429 errors.
- **🧠 Thinking Model Support**: Full support for Gemini 3 and Claude "thinking" models.
- **🔌 Dual Quota System**: Intelligently routes requests between **Antigravity** and **Gemini CLI** quotas.

## 📦 Installation

Requires Python 3.8+.

```bash
# Clone the repository
git clone https://github.com/firdyfirdy/antigravity-auth.git
cd antigravity-auth

# Install in editable mode
pip install -e .
```

## 🚀 Quick Start (CLI)

The library comes with a built-in CLI for managing authentication and testing models.

### 1. Login
Authenticate with your Google account. This opens a browser for standard Google login.

```bash
python -m cli.main auth login
```

### 2. Verify Status
Check your current login status and quota usage.

```bash
python -m cli.main auth status
```

### 3. Test a Model
Send a simple prompt to verify everything is working.

```bash
python -m cli.main auth test --model gemini-3-pro
```

## 🤖 Supported Models & Quotas

This library automatically routes requests to the appropriate quota based on the model name.

| Model Name | Quota / Backend | Capabilities |
|------------|-----------------|--------------|
| **Gemini 3** | | |
| `gemini-3-pro` | **Antigravity** | High-reasoning, "Thinking" model |
| `gemini-3-flash` | **Antigravity** | Fast reasoning |
| `gemini-3-pro-preview` | **Gemini CLI** | Public preview version |
| `gemini-3-flash-preview`| **Gemini CLI** | Public preview version |
| **Gemini 2.5** | | |
| `gemini-2.5-pro` | **Gemini CLI** | Stable production model |
| `gemini-2.5-flash` | **Gemini CLI** | Fast, cost-effective |
| **Claude (Anthropic)** | | |
| `claude-sonnet-4-5` | **Antigravity** | SOTA reasoning (proxied) |
| `claude-opus-4-5` | **Antigravity** | Maximum capability (proxied) |

> **Note:** Models using the **Antigravity** quota require special system instructions, which this library handles automatically.

## 🛠️ Advanced CLI Usage

### Account Management

**List all accounts:**
```bash
python -m cli.main auth list
```

**Switch active account:**
```bash
# Switch to account #2
python -m cli.main auth switch 2
```

**Logout / Remove account:**
```bash
# Interactive selection
python -m cli.main auth logout

# Remove specific email
python -m cli.main auth logout user@example.com

# Remove ALL accounts
python -m cli.main auth logout --all
```

**Test with specific prompt:**
```bash
python -m cli.main auth test -m claude-sonnet-4-5 -p "Explain quantum computing in one sentence."
```

## 💻 Python API Usage

Refactor your tools to use the `AntigravityService` class.

### Basic Generation

```python
from antigravity import AntigravityService

# Initialize service (uses default gemini-3-pro)
service = AntigravityService()

# Or specify a model
# service = AntigravityService(model="claude-sonnet-4-5")

# Generate text
response = service.generate_sync(
    prompt="Write a hello world in Python",
    system_prompt="Be concise."
)

print(response)
```

### Streaming Support

```python
import asyncio
from antigravity import AntigravityService

async def main():
    service = AntigravityService(model="gemini-3-pro")
    
    # Stream response
    async for chunk in service.generate_stream("Tell me a story about a brave knight."):
        print(chunk, end="", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
```

### Accessing the Client Directly

For lower-level access (HTTP requests, raw tokens):

```python
from antigravity import AntigravityService

service = AntigravityService()
client = service.client
account_manager = service.account_manager

# Get a valid access token
token = await account_manager.get_valid_token(permission_type="gemini-antigravity")
print(f"Access Token: {token}")
```

## 🏗️ Architecture

The library is organized into specialized modules:

- **`antigravity.oauth`**: Handles the detailed OAuth 2.0 PKCE flow.
- **`antigravity.token`**: Manages token parsing, expiry tracking, and refreshing.
- **`antigravity.storage`**: Secure JSON persistence for multi-account credentials.
- **`antigravity.client`**: The HTTP client that understands Antigravity's API headers and endpoint fallbacks.
- **`antigravity.service`**: The high-level facade for effortless integration.

## 📜 Credits

This project is a Python implementation of the reverse-engineered authentication flow discovered by **NoeFabris** and the OpenCode community.

- **Original Project**: [opencode-antigravity-auth](https://github.com/NoeFabris/opencode-antigravity-auth)
- **License**: MIT
