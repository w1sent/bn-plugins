#!/usr/bin/env python3
"""Configure AI coding tools to connect to a running Binary Ninja MCP server.

Supports Claude Code, Codex CLI, OpenCode, and DeepAgents
(`langchain-mcp-adapters`). For Claude Code/Codex/OpenCode, this shells out
to each tool's own `mcp add` CLI when it's installed -- those commands
already merge into the tool's existing config safely -- and falls back to a
direct, merge-only edit of the config file otherwise (new entry added,
everything else in the file left untouched; never truncates or overwrites
unrelated content). DeepAgents has no CLI or standard config file --
`MultiServerMCPClient` just takes a Python dict -- so this writes/merges a
small JSON file under our own convention (see --deepagents-config) for you
to load yourself.

Usage:
    python install_mcp_clients.py --api-key KEY
    python install_mcp_clients.py --api-key KEY --clients claude-code,opencode
    python install_mcp_clients.py --no-auth --url http://127.0.0.1:9090/mcp
    python install_mcp_clients.py --api-key KEY --dry-run

The API key is shown by Binary Ninja's Plugins -> MCP Server -> Copy API Key
menu command once the server has started at least once.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

_DEFAULT_URL = "http://127.0.0.1:9090/mcp"
_DEFAULT_NAME = "binja-mcp"
_ALL_CLIENTS = ("claude-code", "codex", "opencode", "deepagents")


class Result:
    def __init__(self, client: str, status: str, message: str):
        self.client = client
        self.status = status  # "ok" | "skipped" | "error"
        self.message = message


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{path} exists but isn't valid JSON ({e}); refusing to touch it") from e


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def configure_claude_code(name: str, url: str, api_key: str, scope: str, dry_run: bool) -> Result:
    """Prefer `claude mcp add` (handles merging into ~/.claude.json or
    .mcp.json itself); fall back to appending directly into a project-local
    .mcp.json (documented, stable format: top-level "mcpServers" object)."""
    if shutil.which("claude"):
        cmd = ["claude", "mcp", "add", "--transport", "http", name, url, "--scope", scope]
        if api_key:
            cmd += ["--header", f"Authorization: Bearer {api_key}"]
        if dry_run:
            return Result("claude-code", "ok", f"[dry-run] would run: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            return Result("claude-code", "ok", f"registered '{name}' via `claude mcp add` (scope={scope})")
        except subprocess.CalledProcessError as e:
            return Result("claude-code", "error", f"`claude mcp add` failed: {e.stderr.strip() or e}")

    path = Path.cwd() / ".mcp.json"
    entry = {"type": "http", "url": url}
    if api_key:
        entry["headers"] = {"Authorization": f"Bearer {api_key}"}
    if dry_run:
        return Result("claude-code", "ok", f"[dry-run] would merge {name!r} into {path} (mcpServers)")
    data = _load_json(path)
    data.setdefault("mcpServers", {})[name] = entry
    _write_json(path, data)
    return Result("claude-code", "ok", f"`claude` CLI not found; appended '{name}' to {path}")


def configure_codex(name: str, url: str, api_key: str, env_var: str, dry_run: bool) -> Result:
    """Prefer `codex mcp add` (writes ~/.codex/config.toml itself, appending
    a new [mcp_servers.<name>] table). Codex only supports reading the
    bearer token from an environment variable, not a literal value in the
    config file -- you must export `env_var` yourself before launching
    codex. Falls back to appending a new TOML table directly if the `codex`
    CLI isn't installed."""
    if shutil.which("codex"):
        cmd = ["codex", "mcp", "add", name, "--url", url]
        if api_key:
            cmd += ["--bearer-token-env-var", env_var]
        if dry_run:
            return Result("codex", "ok", f"[dry-run] would run: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            note = f"; export {env_var}=<your API key> before launching codex" if api_key else ""
            return Result("codex", "ok", f"registered '{name}' via `codex mcp add`{note}")
        except subprocess.CalledProcessError as e:
            return Result("codex", "error", f"`codex mcp add` failed: {e.stderr.strip() or e}")

    path = Path.home() / ".codex" / "config.toml"
    marker = f"[mcp_servers.{name}]"
    existing = path.read_text() if path.exists() else ""
    if marker in existing:
        return Result("codex", "skipped", f"{path} already has a {marker} table; leaving it untouched")
    lines = [marker, f'url = "{url}"']
    if api_key:
        lines.append(f'bearer_token_env_var = "{env_var}"')
    block = "\n".join(lines) + "\n"
    if dry_run:
        return Result("codex", "ok", f"[dry-run] would append to {path}:\n{block}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write("\n" + block)
    note = f"; export {env_var}=<your API key> before launching codex" if api_key else ""
    return Result("codex", "ok", f"`codex` CLI not found; appended '{name}' to {path}{note}")


def configure_opencode(name: str, url: str, api_key: str, dry_run: bool) -> Result:
    """Prefer `opencode mcp add` (merges into opencode's own config file
    itself); fall back to appending directly into
    ~/.config/opencode/opencode.json (top-level "mcp" object)."""
    if shutil.which("opencode"):
        cmd = ["opencode", "mcp", "add", name, "--url", url]
        if api_key:
            cmd += ["--header", f"Authorization=Bearer {api_key}"]
        if dry_run:
            return Result("opencode", "ok", f"[dry-run] would run: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, input="")
            return Result("opencode", "ok", f"registered '{name}' via `opencode mcp add`")
        except subprocess.CalledProcessError as e:
            return Result("opencode", "error", f"`opencode mcp add` failed: {e.stderr.strip() or e}")

    path = Path.home() / ".config" / "opencode" / "opencode.json"
    entry = {"type": "remote", "url": url, "enabled": True}
    if api_key:
        entry["headers"] = {"Authorization": f"Bearer {api_key}"}
    if dry_run:
        return Result("opencode", "ok", f"[dry-run] would merge {name!r} into {path} (mcp)")
    try:
        data = _load_json(path)
    except RuntimeError as e:
        return Result("opencode", "error", str(e))
    data.setdefault("mcp", {})[name] = entry
    _write_json(path, data)
    return Result("opencode", "ok", f"`opencode` CLI not found; appended '{name}' to {path}")


def configure_deepagents(name: str, url: str, api_key: str, config_path: Path, dry_run: bool) -> Result:
    """DeepAgents (langchain-mcp-adapters' MultiServerMCPClient) takes a
    plain Python dict, not a config file -- there's no CLI or standard file
    convention to hook into. This writes/merges a small JSON file (our own
    convention, not an official DeepAgents format) that you load yourself:

        import json
        from langchain_mcp_adapters.client import MultiServerMCPClient
        with open(config_path) as f:
            client = MultiServerMCPClient(json.load(f))
    """
    entry = {"transport": "http", "url": url}
    if api_key:
        entry["headers"] = {"Authorization": f"Bearer {api_key}"}
    if dry_run:
        return Result("deepagents", "ok", f"[dry-run] would merge {name!r} into {config_path}")
    try:
        data = _load_json(config_path)
    except RuntimeError as e:
        return Result("deepagents", "error", str(e))
    data[name] = entry
    _write_json(config_path, data)
    return Result(
        "deepagents",
        "ok",
        f"wrote '{name}' to {config_path} (load with MultiServerMCPClient(json.load(open(...))))",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=_DEFAULT_URL, help=f"MCP endpoint URL (default: {_DEFAULT_URL})")
    parser.add_argument("--name", default=_DEFAULT_NAME, help=f"Server name to register (default: {_DEFAULT_NAME})")
    parser.add_argument("--api-key", help="Binary Ninja MCP server API key (Plugins -> MCP Server -> Copy API Key)")
    parser.add_argument("--no-auth", action="store_true", help="Configure clients with no Authorization header")
    parser.add_argument(
        "--clients",
        default=",".join(_ALL_CLIENTS),
        help=f"Comma-separated subset of {{{','.join(_ALL_CLIENTS)}}} (default: all)",
    )
    parser.add_argument(
        "--claude-scope", default="user", choices=("local", "user", "project"), help="Claude Code config scope"
    )
    parser.add_argument(
        "--codex-env-var",
        default="BINJA_MCP_API_KEY",
        help="Env var name Codex reads the bearer token from (default: BINJA_MCP_API_KEY)",
    )
    parser.add_argument(
        "--deepagents-config",
        default=str(Path.home() / ".config" / "deepagents" / "mcp_config.json"),
        help="Where to write/merge the DeepAgents-convention JSON config",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print what would change without writing anything")
    args = parser.parse_args()

    if not args.api_key and not args.no_auth:
        parser.error("pass --api-key <key> (see Plugins -> MCP Server -> Copy API Key), or --no-auth")

    clients = [c.strip() for c in args.clients.split(",") if c.strip()]
    unknown = set(clients) - set(_ALL_CLIENTS)
    if unknown:
        parser.error(f"unknown client(s): {', '.join(sorted(unknown))}; choose from {_ALL_CLIENTS}")

    api_key = "" if args.no_auth else args.api_key
    results = []

    if "claude-code" in clients:
        results.append(configure_claude_code(args.name, args.url, api_key, args.claude_scope, args.dry_run))
    if "codex" in clients:
        results.append(configure_codex(args.name, args.url, api_key, args.codex_env_var, args.dry_run))
    if "opencode" in clients:
        results.append(configure_opencode(args.name, args.url, api_key, args.dry_run))
    if "deepagents" in clients:
        results.append(
            configure_deepagents(args.name, args.url, api_key, Path(args.deepagents_config), args.dry_run)
        )

    print()
    for r in results:
        marker = {"ok": "[ok]", "skipped": "[skip]", "error": "[error]"}[r.status]
        print(f"{marker} {r.client}: {r.message}")
    print()

    return 1 if any(r.status == "error" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
