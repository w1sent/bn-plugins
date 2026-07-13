#!/usr/bin/env python3
"""Install plugins into Binary Ninja's plugin folder.

Usage:
    python install.py                    # install all plugins (copy mode)
    python install.py --link             # install all plugins (symlink dev mode)
    python install.py --interactive      # interactive selection prompt
    python install.py --plugin-dir PATH   # override BN plugin folder
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def discover_plugins(repo_root):
    plugins = []
    for bucket in ("frameworks", "ai", "ux"):
        bucket_dir = repo_root / bucket
        if not bucket_dir.is_dir():
            continue
        for entry in sorted(bucket_dir.iterdir()):
            if entry.is_dir() and (entry / "__init__.py").exists():
                plugins.append(entry)
    return plugins


def interactive_select(plugins):
    selected = set(plugins)
    print("Select plugins to install (all selected by default):\n")
    for i, p in enumerate(plugins):
        marker = "[x]" if p in selected else "[ ]"
        print(f"  {i+1}. {marker} {p.relative_to(p.parents[1])}")
    print("\nEnter numbers to toggle, or press Enter to confirm all:")
    choice = input("> ").strip()
    if choice:
        for num in choice.split():
            try:
                idx = int(num) - 1
                if 0 <= idx < len(plugins):
                    p = plugins[idx]
                    if p in selected:
                        selected.remove(p)
                    else:
                        selected.add(p)
            except ValueError:
                pass
    return [p for p in plugins if p in selected]


def get_bn_plugin_dir():
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Binary Ninja" / "plugins"
    elif sys.platform == "win32":
        return Path(os.environ.get("APPDATA", "")) / "Binary Ninja" / "plugins"
    else:
        return Path.home() / ".binaryninja" / "plugins"


def install_plugin(plugin_path, bn_plugin_dir, repo_root, use_link):
    dest = bn_plugin_dir / plugin_path.name
    if dest.exists():
        if dest.is_symlink():
            dest.unlink()
        else:
            shutil.rmtree(dest)

    if use_link:
        dest.mkdir()
        for entry in plugin_path.iterdir():
            if entry.name == ".deps":
                continue
            os.symlink(entry.resolve(), dest / entry.name)
        os.symlink((repo_root / "core").resolve(), dest / "core")
        print(f"  linked -> {dest}")
    else:
        shutil.copytree(plugin_path, dest)
        core_src = repo_root / "core"
        core_dest = dest / "core"
        if core_dest.exists():
            shutil.rmtree(core_dest)
        shutil.copytree(core_src, core_dest)
        print(f"  copied -> {dest}")

    req_file = plugin_path / "requirements.txt"
    if req_file.exists():
        deps_dir = dest / ".deps"
        if deps_dir.exists():
            shutil.rmtree(deps_dir)
        deps_dir.mkdir(exist_ok=True)
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "-t", str(deps_dir), "-r", str(req_file)],
            check=True,
        )
        print(f"  deps installed -> {deps_dir}")


def main():
    parser = argparse.ArgumentParser(description="Install Binary Ninja plugins")
    parser.add_argument("--link", action="store_true", help="Symlink plugins (dev mode)")
    parser.add_argument("--interactive", action="store_true", help="Interactive selection prompt")
    parser.add_argument("--plugin-dir", type=Path, help="Override BN plugin folder")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    plugins = discover_plugins(repo_root)

    if not plugins:
        print("No plugins found.")
        return

    if args.interactive:
        plugins = interactive_select(plugins)

    bn_plugin_dir = args.plugin_dir or get_bn_plugin_dir()
    bn_plugin_dir.mkdir(parents=True, exist_ok=True)

    mode = "link" if args.link else "copy"
    print(f"Installing {len(plugins)} plugin(s) to {bn_plugin_dir} ({mode} mode):\n")

    for plugin_path in plugins:
        install_plugin(plugin_path, bn_plugin_dir, repo_root, args.link)

    print("\nDone.")


if __name__ == "__main__":
    main()
