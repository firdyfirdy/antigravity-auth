"""
Antigravity CLI

Command-line interface for managing Antigravity authentication.
"""

import asyncio
import sys
import webbrowser
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# Add parent directory to path for imports
# sys.path.insert(0, str(__file__).rsplit("cli", 1)[0] + "src")

from antigravity_auth import (
    AntigravityService,
    AntigravityError,
    NoAccountsError,
    AllAccountsRateLimitedError,
    build_authorization_url,
    exchange_code_for_tokens,
    load_accounts,
    add_or_update_account,
    remove_account_by_email,
    set_active_account,
    clear_accounts,
    get_storage_path,
)
from antigravity_auth.server import OAuthListener, parse_callback_url
from antigravity_auth.token import parse_refresh_parts


app = typer.Typer(
    name="antigravity",
    help="Antigravity authentication CLI for Google Gemini and Claude models.",
    no_args_is_help=True,
)
console = Console()


# Auth subcommand group
auth_app = typer.Typer(help="Manage authentication and accounts.")
app.add_typer(auth_app, name="auth")


@auth_app.command("login")
def auth_login(
    manual: bool = typer.Option(False, "--manual", "-m", help="Use manual code entry instead of callback server"),
):
    """
    Login with a Google account to add or update an Antigravity account.
    """
    console.print("\n[bold blue]🔐 Antigravity Login[/bold blue]\n")
    
    # Generate authorization URL
    auth_result = build_authorization_url()
    
    console.print(f"[dim]Opening browser for authentication...[/dim]\n")
    console.print(f"[yellow]If the browser doesn't open, visit this URL:[/yellow]")
    console.print(f"[link={auth_result.url}]{auth_result.url}[/link]\n")
    
    # Try to open browser
    try:
        webbrowser.open(auth_result.url)
    except Exception:
        pass
    
    if manual:
        # Manual code entry
        console.print("[cyan]After signing in, paste the redirect URL or code here:[/cyan]")
        callback_input = typer.prompt("URL or code")
        
        # Parse input
        if callback_input.startswith("http"):
            code, state = parse_callback_url(callback_input)
            if not state:
                # Use the state from our authorization
                from antigravity_auth.oauth import encode_state
                state = encode_state(auth_result.verifier, auth_result.project_id)
        else:
            code = callback_input.strip()
            from antigravity_auth.oauth import encode_state
            state = encode_state(auth_result.verifier, auth_result.project_id)
        
        if not code:
            console.print("[red]Error: Invalid callback URL or code[/red]")
            raise typer.Exit(1)
    else:
        # Start callback server
        listener = OAuthListener()
        
        if not listener.start():
            console.print("[yellow]Could not start callback server. Falling back to manual mode.[/yellow]")
            console.print("[cyan]After signing in, paste the redirect URL here:[/cyan]")
            callback_input = typer.prompt("Redirect URL")
            code, state = parse_callback_url(callback_input)
            
            if not state:
                from antigravity_auth.oauth import encode_state
                state = encode_state(auth_result.verifier, auth_result.project_id)
            
            if not code:
                console.print("[red]Error: Invalid callback URL[/red]")
                raise typer.Exit(1)
        else:
            console.print("[dim]Waiting for authorization (timeout: 5 minutes)...[/dim]")
            
            callback_url = listener.wait_for_callback()
            listener.stop()
            
            if not callback_url:
                console.print("[red]Error: Authorization timed out[/red]")
                raise typer.Exit(1)
            
            code, state = parse_callback_url(callback_url)
            
            if not code or not state:
                console.print("[red]Error: Invalid callback[/red]")
                raise typer.Exit(1)
    
    # Exchange code for tokens
    console.print("[dim]Exchanging authorization code...[/dim]")
    
    result = asyncio.run(exchange_code_for_tokens(code, state))
    
    if not result.success:
        console.print(f"[red]Error: {result.error}[/red]")
        raise typer.Exit(1)
    
    # Extract refresh token parts
    parts = parse_refresh_parts(result.refresh_token or "")
    
    # Save account
    add_or_update_account(
        email=result.email,
        refresh_token=parts.refresh_token,
        project_id=result.project_id,
        managed_project_id=parts.managed_project_id,
    )
    
    console.print(f"\n[green]✅ Successfully logged in as {result.email}[/green]")
    console.print(f"[dim]Project ID: {result.project_id or 'default'}[/dim]\n")


@auth_app.command("list")
def auth_list():
    """
    List all configured Antigravity accounts.
    """
    storage = load_accounts()
    
    if not storage or not storage.accounts:
        console.print("[yellow]No accounts configured. Run 'antigravity auth login' to add one.[/yellow]")
        return
    
    table = Table(title="Antigravity Accounts")
    table.add_column("#", style="dim", width=3)
    table.add_column("Email", style="cyan")
    table.add_column("Project ID", style="green")
    table.add_column("Status", style="yellow")
    
    for i, account in enumerate(storage.accounts):
        status = "✓ Active" if i == storage.active_index else ""
        table.add_row(
            str(i + 1),
            account.email or "(unknown)",
            account.project_id or "(default)",
            status,
        )
    
    console.print(table)
    console.print(f"\n[dim]Storage: {get_storage_path()}[/dim]")


@auth_app.command("status")
def auth_status():
    """
    Show the current authentication status.
    """
    storage = load_accounts()
    
    if not storage or not storage.accounts:
        console.print(Panel.fit(
            "[yellow]Not logged in[/yellow]\n\nRun 'antigravity auth login' to add an account.",
            title="Authentication Status",
        ))
        return
    
    active_account = storage.accounts[storage.active_index] if storage.accounts else None
    
    if active_account:
        content = f"""[green]Logged in[/green]

[bold]Email:[/bold] {active_account.email or '(unknown)'}
[bold]Project ID:[/bold] {active_account.project_id or '(default)'}
[bold]Accounts:[/bold] {len(storage.accounts)}
[bold]Active:[/bold] #{storage.active_index + 1}"""
        
        console.print(Panel.fit(content, title="Authentication Status"))
    else:
        console.print("[yellow]No active account[/yellow]")


@auth_app.command("switch")
def auth_switch(
    index: int = typer.Argument(..., help="Account number to switch to (1-based)"),
):
    """
    Switch to a different account.
    """
    storage = load_accounts()
    
    if not storage or not storage.accounts:
        console.print("[red]No accounts configured.[/red]")
        raise typer.Exit(1)
    
    # Convert to 0-based index
    idx = index - 1
    
    if idx < 0 or idx >= len(storage.accounts):
        console.print(f"[red]Invalid account number. Choose 1-{len(storage.accounts)}.[/red]")
        raise typer.Exit(1)
    
    if set_active_account(idx):
        account = storage.accounts[idx]
        console.print(f"[green]Switched to account #{index}: {account.email or '(unknown)'}[/green]")
    else:
        console.print("[red]Failed to switch account.[/red]")
        raise typer.Exit(1)


@auth_app.command("logout")
def auth_logout(
    email: Optional[str] = typer.Argument(None, help="Email of account to remove"),
    all_accounts: bool = typer.Option(False, "--all", "-a", help="Remove all accounts"),
):
    """
    Logout and remove an account.
    """
    if all_accounts:
        if typer.confirm("Are you sure you want to remove ALL accounts?"):
            clear_accounts()
            console.print("[green]All accounts removed.[/green]")
        return
    
    storage = load_accounts()
    
    if not storage or not storage.accounts:
        console.print("[yellow]No accounts configured.[/yellow]")
        return
    
    if email:
        if remove_account_by_email(email):
            console.print(f"[green]Removed account: {email}[/green]")
        else:
            console.print(f"[red]Account not found: {email}[/red]")
            raise typer.Exit(1)
    else:
        # Show accounts and ask which to remove
        console.print("Select account to remove:\n")
        for i, account in enumerate(storage.accounts):
            console.print(f"  {i + 1}. {account.email or '(unknown)'}")
        
        choice = typer.prompt("\nAccount number", type=int)
        idx = choice - 1
        
        if idx < 0 or idx >= len(storage.accounts):
            console.print("[red]Invalid choice.[/red]")
            raise typer.Exit(1)
        
        account = storage.accounts[idx]
        if account.email:
            remove_account_by_email(account.email)
            console.print(f"[green]Removed account: {account.email}[/green]")
        else:
            console.print("[red]Cannot remove account without email.[/red]")
            raise typer.Exit(1)


@auth_app.command("test")
def auth_test(
    prompt: str = typer.Option("What is 2 + 2? Answer in one word.", "--prompt", "-p", help="Test prompt"),
    model: str = typer.Option("gemini-3-pro", "--model", "-m", help="Model to use"),
):
    """
    Test authentication with a simple prompt.
    """
    console.print(f"\n[bold blue]🧪 Testing Antigravity with {model}[/bold blue]\n")
    console.print(f"[dim]Prompt: {prompt}[/dim]\n")
    
    try:
        service = AntigravityService(model=model)
        response = service.generate_sync(prompt=prompt)
        
        console.print(Panel.fit(
            response,
            title="Response",
            border_style="green",
        ))
        console.print("\n[green]✅ Authentication working![/green]\n")
        
    except NoAccountsError:
        console.print("[red]No accounts configured. Run 'antigravity auth login' first.[/red]")
        raise typer.Exit(1)
    except AllAccountsRateLimitedError as e:
        console.print(f"[yellow]All accounts rate-limited. Try again in {e.wait_time_ms // 1000}s.[/yellow]")
        raise typer.Exit(1)
    except AntigravityError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command("version")
def version():
    """Show the version."""
    from antigravity_auth import __version__
    console.print(f"antigravity {__version__}")


def main():
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()
