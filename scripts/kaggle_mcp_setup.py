#!/usr/bin/env python3
"""One-command onboarding: validate Kaggle credentials and write the client config.

Usage:
    uv run python scripts/kaggle_mcp_setup.py --client desktop [--dry-run]
    uv run python scripts/kaggle_mcp_setup.py --client code   # prints the CLI command

Never writes real API keys into a shared/project file — it points the config at your
environment. Credentials are validated out-of-band (env or ~/.kaggle/kaggle.json).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _validate_credentials() -> str | None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    try:
        from kaggle_mcp import auth  # noqa: WPS433
        creds = auth.resolve()
        return creds.username
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ credential check failed: {e}", file=sys.stderr)
        return None


def _desktop_config_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
    if sys.platform.startswith("win"):
        import os
        return Path(os.environ["APPDATA"]) / "Claude/claude_desktop_config.json"
    return Path.home() / ".config/Claude/claude_desktop_config.json"


def _server_entry() -> dict:
    return {
        "command": "uvx",
        "args": ["kaggle-mcp"],
        "env": {"KAGGLE_USERNAME": "REPLACE_ME", "KAGGLE_KEY": "REPLACE_ME"},
    }


def setup_desktop(dry_run: bool) -> int:
    path = _desktop_config_path()
    config = {}
    if path.exists():
        try:
            config = json.loads(path.read_text())
        except json.JSONDecodeError:
            print(f"  ✗ existing config is not valid JSON: {path}", file=sys.stderr)
            return 1
    config.setdefault("mcpServers", {})["kaggle"] = _server_entry()
    rendered = json.dumps(config, indent=2)
    if dry_run:
        print(f"  (dry-run) would write to {path}:\n{rendered}")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered)
    print(f"  ✓ wrote {path}")
    print("  → Replace REPLACE_ME with your KAGGLE_USERNAME/KAGGLE_KEY, then fully restart Claude Desktop.")
    return 0


def setup_code() -> int:
    print("  Run this to register with Claude Code:\n")
    print("    claude mcp add --transport stdio \\")
    print("      --env KAGGLE_USERNAME=your_user --env KAGGLE_KEY=your_key \\")
    print("      kaggle -- uvx kaggle-mcp\n")
    print("  Verify with:  claude mcp list   (expect: kaggle  ✓ Connected)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Set up kaggle-mcp for a Claude client.")
    ap.add_argument("--client", choices=["desktop", "code"], default="desktop")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("Checking Kaggle credentials...")
    username = _validate_credentials()
    if username:
        print(f"  ✓ credentials resolved for '{username}'")
    else:
        print("  ! No credentials found yet — set KAGGLE_USERNAME/KAGGLE_KEY or place kaggle.json.")

    print(f"\nConfiguring Claude {args.client}...")
    return setup_desktop(args.dry_run) if args.client == "desktop" else setup_code()


if __name__ == "__main__":
    raise SystemExit(main())
