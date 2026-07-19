"""CLI entry point: `empower-mcp setup|serve|status`.

`setup` is interactive (email/password + 2FA) and must be run in a real
terminal, outside of Claude. `serve` is what the MCP client launches.

Secrets hygiene: the password is read with getpass, kept only in local
variables, and never printed or logged. Session cookies are written only to
the 0600 session file, never to stdout/stderr.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from .client import (
    ApiError,
    EmpowerClient,
    EmpowerError,
    SessionExpiredError,
    default_session_path,
)


def cmd_setup(args: argparse.Namespace) -> int:
    print("Empower Personal Dashboard — first-time setup")
    print(f"Session will be stored at: {default_session_path()} (chmod 600)")
    print()

    email = args.email or input("Empower email: ").strip()
    if not email:
        print("No email given; aborting.", file=sys.stderr)
        return 1
    password = getpass.getpass("Empower password (not stored, not echoed): ")

    client = EmpowerClient()
    try:
        client.fetch_initial_csrf()
        auth_level = client.identify_user(email)

        if auth_level != "USER_REMEMBERED":
            method = args.method
            while method not in ("sms", "email"):
                method = input("2FA method — 'sms' or 'email': ").strip().lower()
            client.challenge_two_factor(method)
            print(f"A verification code was sent via {method}.")
            code = input("Enter the 2FA code: ").strip()
            client.authenticate_two_factor(method, code)

        client.authenticate_password(password)
    except EmpowerError as exc:
        print(f"\nSetup failed: {exc}", file=sys.stderr)
        return 1
    finally:
        # Drop the password reference promptly; it is not persisted anywhere.
        del password

    try:
        accounts = client.get_accounts().get("accounts") or []
    except EmpowerError as exc:
        print(f"\nAuthenticated, but test fetch failed: {exc}", file=sys.stderr)
        return 1
    print(f"\nAuthenticated successfully. Found {len(accounts)} linked accounts.")
    print("You can now use the MCP server from Claude Desktop/Code.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    path = default_session_path()
    if not path.exists():
        print(f"No session file at {path}. Run `empower-mcp setup`.")
        return 1
    client = EmpowerClient()
    if not client.load_session():
        print(f"Session file at {path} is unreadable. Re-run `empower-mcp setup`.")
        return 1
    try:
        accounts = client.get_accounts().get("accounts") or []
    except SessionExpiredError:
        print("Session has expired. Re-run `empower-mcp setup`.")
        return 1
    except ApiError as exc:
        print(f"Session file present but API check failed: {exc}", file=sys.stderr)
        return 1
    print(f"Session is valid. {len(accounts)} linked accounts visible.")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import run

    run()
    return 0


def cmd_logout(args: argparse.Namespace) -> int:
    client = EmpowerClient()
    client.clear_session()
    print(f"Removed local session file (if any) at {default_session_path()}.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="empower-mcp",
        description="Local, read-only MCP server for Empower Personal Dashboard.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_setup = sub.add_parser("setup", help="Interactive login + 2FA (run once, in a terminal)")
    p_setup.add_argument("--email", help="Empower login email (prompted if omitted)")
    p_setup.add_argument(
        "--method", choices=["sms", "email"], help="2FA delivery method (prompted if omitted)"
    )
    p_setup.set_defaults(func=cmd_setup)

    p_serve = sub.add_parser("serve", help="Run the MCP server on stdio (launched by the MCP client)")
    p_serve.set_defaults(func=cmd_serve)

    p_status = sub.add_parser("status", help="Check whether the stored session is still valid")
    p_status.set_defaults(func=cmd_status)

    p_logout = sub.add_parser("logout", help="Delete the local session file")
    p_logout.set_defaults(func=cmd_logout)

    args = parser.parse_args()
    sys.exit(args.func(args))
