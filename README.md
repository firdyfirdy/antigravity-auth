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

## ⚙️ Configuration

### Custom Storage Location
By default, the library stores credentials in:
- **Windows**: `%APPDATA%\antigravity_auth`
- **Linux/Mac**: `~/.config/antigravity_auth`

You can override this by setting the `ANTIGRAVITY_STORAGE_PATH` environment variable to point to a specific file:
 
 ```bash
 # Windows
 set ANTIGRAVITY_STORAGE_PATH=C:\My\Custom\path\to\accounts.json
 
 # Linux/Mac
 export ANTIGRAVITY_STORAGE_PATH=/path/to/custom/accounts.json
 ```
 
 Or by passing the `--storage-path` flag to any CLI command:
 
 ```bash
 antigravity-auth auth list --storage-path "C:\My\Custom\accounts.json"
 ```

## 🚀 Quick Start (CLI)

The library comes with a built-in CLI for managing authentication and testing models.

### 1. Login
Authenticate with your Google account. This opens a browser for standard Google login.

```bash
python -m cli.main auth login
# OR
antigravity-auth auth login
```

### 2. Verify Status
Check your current login status and quota usage.

```bash
antigravity-auth auth status
```

### 3. Test a Model
Send a simple prompt to verify everything is working.

```bash
antigravity-auth auth test --model gemini-3-pro
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
| `claude-sonnet-4-5-thinking` | **Antigravity** | SOTA reasoning (proxied) |
| `claude-opus-4-5-thinking` | **Antigravity** | Maximum capability (proxied) |

> **Note:** Models using the **Antigravity** quota require special system instructions, which this library handles automatically.

## 🛠️ Advanced CLI Usage

### Account Management

**List all accounts:**
```bash
antigravity-auth auth list
```

**Switch active account:**
```bash
# Switch to account #2
antigravity-auth auth switch 2
```

**Logout / Remove account:**
```bash
# Interactive selection
antigravity-auth auth logout

# Remove specific email
antigravity-auth auth logout user@example.com

# Remove ALL accounts
antigravity-auth auth logout --all
```

**Test with specific prompt:**
```bash
antigravity-auth auth test -m claude-sonnet-4-5 -p "Explain quantum computing in one sentence."
```

## 🌐 API Server (OpenAI Compatible)

Run Antigravity as a local API server that's compatible with OpenAI clients.

### Start the Server
```bash
# Install server dependencies
pip install -e .[server]

# Start server on default port 8069
antigravity-auth serve

# Or specify host/port
antigravity-auth serve --host 0.0.0.0 --port 8069
```

### API Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/v1/models` | GET | List available models |
| `/v1/chat/completions` | POST | Generate chat completion |

### Usage with curl
```bash
curl http://localhost:8069/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "gemini-3-pro", "messages": [{"role": "user", "content": "Hello!"}]}'
```

### Usage with OpenAI Python Client
```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8069/v1", api_key="dummy")
response = client.chat.completions.create(
    model="gemini-3-pro",
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)
```

## 💻 Python API Usage

Refactor your tools to use the `AntigravityService` class.

### Basic Generation

```python
from antigravity import AntigravityService

# Initialize service (uses default gemini-3-pro)
service = AntigravityService()

# Specify custom storage path
# service = AntigravityService(storage_path="/path/to/accounts.json")

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

## ⚠️ Disclaimer

This project is for **educational and research purposes only**. It comes with no warranty or support.

This library interacts with internal Google APIs solely to demonstrate the authentication flows and API mechanics described in public reverse-engineering research. It is **not** an official Google product. 

Using this software may violate Google's Terms of Service. The authors and contributors are not responsible for any actions taken by users of this code, nor for any consequences that may result, including but not limited to account suspension or termination. Use at your own risk.
