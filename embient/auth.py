"""Authentication module for Embient CLI.

Provides Claude Code-style authentication with browser-based OAuth flow
and secure local credential storage.

Usage:
    # Login
    embient login

    # Check auth status
    embient status

    # Logout
    embient logout
"""

import json
import os
import secrets
import sys
import threading
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse

from rich.console import Console

console = Console()

# Default Basement API URL
DEFAULT_BASEMENT_API = "https://basement.embient.ai"

# Local callback server port
CALLBACK_PORT = 8787


def get_embient_dir() -> Path:
    """Get the .embient directory path, creating it if needed."""
    embient_dir = Path.home() / ".embient"
    embient_dir.mkdir(parents=True, exist_ok=True)
    return embient_dir


def get_credentials_path() -> Path:
    """Get the path to the credentials file."""
    return get_embient_dir() / "credentials.json"


@dataclass
class Credentials:
    """Stored authentication credentials."""

    jwt_token: str
    refresh_token: Optional[str]
    expires_at: Optional[str]  # ISO format
    user_id: Optional[str]
    email: Optional[str]

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON storage."""
        return {
            "jwt_token": self.jwt_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "user_id": self.user_id,
            "email": self.email,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Credentials":
        """Create from dictionary."""
        return cls(
            jwt_token=data.get("jwt_token", ""),
            refresh_token=data.get("refresh_token"),
            expires_at=data.get("expires_at"),
            user_id=data.get("user_id"),
            email=data.get("email"),
        )

    def is_expired(self) -> bool:
        """Check if the token is expired."""
        if not self.expires_at:
            return False
        try:
            expires = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
            return datetime.now(timezone.utc) >= expires
        except (ValueError, TypeError):
            return False


def save_credentials(credentials: Credentials) -> None:
    """Save credentials to the credentials file.

    Args:
        credentials: Credentials object to save
    """
    creds_path = get_credentials_path()
    # Ensure parent directory exists
    creds_path.parent.mkdir(parents=True, exist_ok=True)
    # Write with restrictive permissions
    creds_path.write_text(json.dumps(credentials.to_dict(), indent=2))
    # Set file permissions to owner-only (Unix)
    try:
        os.chmod(creds_path, 0o600)
    except OSError:
        pass  # Windows doesn't support chmod


def load_credentials() -> Optional[Credentials]:
    """Load credentials from the credentials file.

    Returns:
        Credentials object if found and valid, None otherwise
    """
    creds_path = get_credentials_path()
    if not creds_path.exists():
        return None

    try:
        data = json.loads(creds_path.read_text())
        credentials = Credentials.from_dict(data)
        # Check if token exists
        if not credentials.jwt_token:
            return None
        return credentials
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def clear_credentials() -> bool:
    """Remove stored credentials.

    Returns:
        True if credentials were removed, False if none existed
    """
    creds_path = get_credentials_path()
    if creds_path.exists():
        creds_path.unlink()
        return True
    return False


def is_authenticated() -> bool:
    """Check if user is authenticated with valid, non-expired credentials.

    Returns:
        True if authenticated with valid token, False otherwise
    """
    credentials = load_credentials()
    if not credentials:
        return False
    if credentials.is_expired():
        return False
    return True


def get_jwt_token() -> Optional[str]:
    """Get the stored JWT token if authenticated.

    Returns:
        JWT token string if authenticated, None otherwise
    """
    credentials = load_credentials()
    if not credentials or credentials.is_expired():
        return None
    return credentials.jwt_token


class CallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler for OAuth callback."""

    credentials: Optional[Credentials] = None
    error: Optional[str] = None

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        """Suppress default logging."""
        pass

    def do_GET(self) -> None:
        """Handle GET request from OAuth callback."""
        parsed = urlparse(self.path)

        if parsed.path == "/callback":
            params = parse_qs(parsed.query)

            # Check for error
            if "error" in params:
                CallbackHandler.error = params.get("error_description", ["Unknown error"])[0]
                self._send_response("Authentication failed. You can close this window.")
                return

            # Extract tokens
            access_token = params.get("access_token", [None])[0]
            refresh_token = params.get("refresh_token", [None])[0]
            expires_in = params.get("expires_in", [None])[0]
            user_id = params.get("user_id", [None])[0]
            email = params.get("email", [None])[0]

            if not access_token:
                CallbackHandler.error = "No access token received"
                self._send_response("Authentication failed. You can close this window.")
                return

            # Calculate expiry
            expires_at = None
            if expires_in:
                try:
                    expires_at = (
                        datetime.now(timezone.utc)
                        .replace(microsecond=0)
                        .isoformat()
                        .replace("+00:00", "Z")
                    )
                    # Add seconds to current time
                    from datetime import timedelta

                    expires_at = (
                        (datetime.now(timezone.utc) + timedelta(seconds=int(expires_in)))
                        .replace(microsecond=0)
                        .isoformat()
                        .replace("+00:00", "Z")
                    )
                except (ValueError, TypeError):
                    pass

            CallbackHandler.credentials = Credentials(
                jwt_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
                user_id=user_id,
                email=email,
            )
            self._send_response(
                "Authentication successful! You can close this window and return to the terminal."
            )
        else:
            self.send_error(404)

    def _send_response(self, message: str) -> None:
        """Send HTML response."""
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Embient CLI Authentication</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    margin: 0;
                    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                    color: #eee;
                }}
                .container {{
                    text-align: center;
                    padding: 2rem;
                    background: rgba(255, 255, 255, 0.1);
                    border-radius: 12px;
                    backdrop-filter: blur(10px);
                }}
                h1 {{ color: #10b981; margin-bottom: 1rem; }}
                p {{ color: #ccc; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Embient</h1>
                <p>{message}</p>
            </div>
        </body>
        </html>
        """
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())


def login_interactive(basement_api: Optional[str] = None) -> bool:
    """Perform interactive browser-based login.

    Opens browser to Basement auth URL and starts local callback server.

    Args:
        basement_api: Optional Basement API URL override

    Returns:
        True if login successful, False otherwise
    """
    api_url = basement_api or os.environ.get("BASEMENT_API", DEFAULT_BASEMENT_API)

    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)

    # Build auth URL
    callback_url = f"http://localhost:{CALLBACK_PORT}/callback"
    auth_params = {
        "redirect_uri": callback_url,
        "state": state,
        "response_type": "token",
        "client_id": "embient-cli",
    }
    auth_url = f"{api_url}/auth/cli?{urlencode(auth_params)}"

    # Reset handler state
    CallbackHandler.credentials = None
    CallbackHandler.error = None

    # Start callback server in background thread
    server = HTTPServer(("localhost", CALLBACK_PORT), CallbackHandler)
    server_thread = threading.Thread(target=server.handle_request)
    server_thread.daemon = True
    server_thread.start()

    console.print("\n[bold]Opening browser for authentication...[/bold]")
    console.print(f"[dim]If browser doesn't open, visit:[/dim]\n{auth_url}\n")

    # Open browser
    try:
        webbrowser.open(auth_url)
    except Exception:  # noqa: BLE001
        console.print("[yellow]Could not open browser automatically.[/yellow]")
        console.print(f"Please open this URL manually:\n{auth_url}")

    console.print("[dim]Waiting for authentication...[/dim]")

    # Wait for callback (with timeout)
    server_thread.join(timeout=300)  # 5 minute timeout

    # Shutdown server
    server.server_close()

    # Check results
    if CallbackHandler.error:
        console.print(f"\n[red]Authentication failed:[/red] {CallbackHandler.error}")
        return False

    if not CallbackHandler.credentials:
        console.print("\n[red]Authentication timed out or was cancelled.[/red]")
        return False

    # Save credentials
    save_credentials(CallbackHandler.credentials)

    console.print("\n[green]Successfully authenticated![/green]")
    if CallbackHandler.credentials.email:
        console.print(f"[dim]Logged in as:[/dim] {CallbackHandler.credentials.email}")

    return True


def login_with_token(token: str) -> bool:
    """Login with a provided JWT token (for automation/testing).

    Args:
        token: JWT token to use

    Returns:
        True if token was saved successfully
    """
    credentials = Credentials(
        jwt_token=token,
        refresh_token=None,
        expires_at=None,
        user_id=None,
        email=None,
    )
    save_credentials(credentials)
    return True


async def login_command() -> None:
    """CLI handler for: embient login."""
    if is_authenticated():
        credentials = load_credentials()
        console.print("[yellow]Already authenticated.[/yellow]")
        if credentials and credentials.email:
            console.print(f"[dim]Logged in as:[/dim] {credentials.email}")
        console.print("[dim]Use 'embient logout' to sign out first.[/dim]")
        return

    success = login_interactive()
    if not success:
        sys.exit(1)


async def logout_command() -> None:
    """CLI handler for: embient logout."""
    if clear_credentials():
        console.print("[green]Successfully logged out.[/green]")
    else:
        console.print("[yellow]No credentials found.[/yellow]")


async def status_command() -> None:
    """CLI handler for: embient status."""
    credentials = load_credentials()

    if not credentials:
        console.print("[yellow]Not authenticated[/yellow]")
        console.print("[dim]Run 'embient login' to authenticate.[/dim]")
        return

    if credentials.is_expired():
        console.print("[yellow]Authentication expired[/yellow]")
        console.print("[dim]Run 'embient login' to re-authenticate.[/dim]")
        return

    console.print("[green]Authenticated[/green]")
    if credentials.email:
        console.print(f"[dim]Email:[/dim] {credentials.email}")
    if credentials.user_id:
        console.print(f"[dim]User ID:[/dim] {credentials.user_id}")
    if credentials.expires_at:
        console.print(f"[dim]Expires:[/dim] {credentials.expires_at}")
