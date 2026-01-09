"""
Antigravity OAuth Callback Server

This module provides a local HTTP server to receive OAuth callbacks
during the login flow.
"""

import asyncio
import socket
import threading
from concurrent.futures import Future
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional
from urllib.parse import parse_qs, urlparse

from .constants import ANTIGRAVITY_REDIRECT_PORT


# HTML page shown after successful OAuth callback
SUCCESS_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Antigravity Auth</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap');
        
        * { box-sizing: border-box; }
        
        body {
            font-family: 'JetBrains Mono', monospace;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            background: #0a0a0f;
            overflow: hidden;
        }
        
        /* Animated grid background */
        body::before {
            content: '';
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: 
                linear-gradient(90deg, rgba(0,255,136,0.03) 1px, transparent 1px),
                linear-gradient(rgba(0,255,136,0.03) 1px, transparent 1px);
            background-size: 50px 50px;
            animation: gridMove 20s linear infinite;
        }
        
        @keyframes gridMove {
            0% { transform: translate(0, 0); }
            100% { transform: translate(50px, 50px); }
        }
        
        .container {
            position: relative;
            text-align: center;
            background: rgba(10, 10, 15, 0.95);
            padding: 50px 70px;
            border: 1px solid #00ff88;
            border-radius: 4px;
            box-shadow: 
                0 0 30px rgba(0,255,136,0.2),
                inset 0 0 30px rgba(0,255,136,0.05);
            z-index: 1;
        }
        
        .container::before {
            content: '';
            position: absolute;
            top: -2px; left: -2px; right: -2px; bottom: -2px;
            background: linear-gradient(45deg, #00ff88, #00ccff, #00ff88);
            border-radius: 6px;
            z-index: -1;
            opacity: 0.5;
            filter: blur(10px);
            animation: glow 3s ease-in-out infinite alternate;
        }
        
        @keyframes glow {
            from { opacity: 0.3; }
            to { opacity: 0.6; }
        }
        
        .icon {
            font-size: 3em;
            margin-bottom: 20px;
            animation: pulse 2s ease-in-out infinite;
        }
        
        @keyframes pulse {
            0%, 100% { transform: scale(1); opacity: 1; }
            50% { transform: scale(1.1); opacity: 0.8; }
        }
        
        h1 {
            color: #00ff88;
            font-size: 1.8em;
            margin: 0 0 15px 0;
            text-transform: uppercase;
            letter-spacing: 3px;
            text-shadow: 0 0 20px rgba(0,255,136,0.5);
        }
        
        .status {
            color: #00ff88;
            font-size: 0.85em;
            margin-bottom: 20px;
            opacity: 0.8;
        }
        
        .status::before {
            content: '> ';
            opacity: 0.5;
        }
        
        p {
            color: #666;
            font-size: 0.9em;
            margin: 0;
        }
        
        .typing {
            overflow: hidden;
            white-space: nowrap;
            animation: typing 2s steps(40, end);
        }
        
        @keyframes typing {
            from { width: 0; }
            to { width: 100%; }
        }
        
        /* Scanline effect */
        .container::after {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            background: repeating-linear-gradient(
                0deg,
                transparent,
                transparent 2px,
                rgba(0,0,0,0.1) 2px,
                rgba(0,0,0,0.1) 4px
            );
            pointer-events: none;
            border-radius: 4px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">🔓</div>
        <h1>Access Granted</h1>
        <div class="status">authentication_successful</div>
        <p class="typing">You may close this window and return to terminal.</p>
    </div>
</body>
</html>
"""



class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP request handler for OAuth callbacks."""
    
    callback_result: Optional[str] = None
    callback_future: Optional[Future] = None
    
    def log_message(self, format, *args):
        """Suppress HTTP server logging."""
        pass
    
    def do_GET(self):
        """Handle GET request - the OAuth callback."""
        parsed = urlparse(self.path)
        
        if parsed.path != "/oauth-callback":
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Not found")
            return
        
        # Parse query parameters
        query = parse_qs(parsed.query)
        code = query.get("code", [None])[0]
        state = query.get("state", [None])[0]
        
        if not code:
            self.send_response(400)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Missing authorization code")
            return
        
        # Send success page
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(SUCCESS_HTML.encode("utf-8"))
        
        # Store the callback URL for processing
        callback_url = f"http://localhost:{ANTIGRAVITY_REDIRECT_PORT}{self.path}"
        
        if OAuthCallbackHandler.callback_future:
            OAuthCallbackHandler.callback_future.set_result(callback_url)


class OAuthListener:
    """
    OAuth callback listener that starts a local HTTP server.
    """
    
    def __init__(self, port: int = ANTIGRAVITY_REDIRECT_PORT, timeout: float = 300.0):
        """
        Initialize the OAuth listener.
        
        Args:
            port: Port to listen on
            timeout: Timeout in seconds for waiting for callback
        """
        self.port = port
        self.timeout = timeout
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._future: Future = Future()
    
    def _is_port_available(self) -> bool:
        """Check if the port is available."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            sock.bind(("localhost", self.port))
            sock.close()
            return True
        except socket.error:
            return False
    
    def start(self) -> bool:
        """
        Start the OAuth callback server.
        
        Returns:
            True if server started successfully
        """
        if not self._is_port_available():
            return False
        
        try:
            OAuthCallbackHandler.callback_future = self._future
            self._server = HTTPServer(("localhost", self.port), OAuthCallbackHandler)
            self._thread = threading.Thread(target=self._server.serve_forever)
            self._thread.daemon = True
            self._thread.start()
            return True
        except Exception:
            return False
    
    def wait_for_callback(self) -> Optional[str]:
        """
        Wait for the OAuth callback.
        
        Returns:
            The callback URL or None if timed out
        """
        try:
            return self._future.result(timeout=self.timeout)
        except Exception:
            return None
    
    async def wait_for_callback_async(self) -> Optional[str]:
        """
        Asynchronously wait for the OAuth callback.
        
        Returns:
            The callback URL or None if timed out
        """
        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, self._future.result),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            return None
    
    def stop(self):
        """Stop the OAuth callback server."""
        if self._server:
            self._server.shutdown()
            self._server = None
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None


def parse_callback_url(url: str) -> tuple[Optional[str], Optional[str]]:
    """
    Parse OAuth callback URL to extract code and state.
    
    Args:
        url: The callback URL
        
    Returns:
        Tuple of (code, state)
    """
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    
    code = query.get("code", [None])[0]
    state = query.get("state", [None])[0]
    
    return code, state
