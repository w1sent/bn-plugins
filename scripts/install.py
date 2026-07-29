#!/usr/bin/env python3
"""Install plugins into Binary Ninja's plugin folder.

Usage:
    python install.py                    # install all plugins (copy mode)
    python install.py --link             # install all plugins (symlink dev mode)
    python install.py --interactive      # interactive selection prompt
    python install.py --plugin-dir PATH   # override BN plugin folder
    python install.py --install-external # also install/update third-party plugins (see below)

Third-party plugins are external, upstream repos (currently the Vector 35
plugins Blob Extractor, Kaitai UI Plugin, Snippets UI Plugin, and Tanto)
that aren't part of this project and aren't affected by --link -- they're
always installed as plain git clones (or updated with `git pull` if already
present), regardless of --link. They're only touched when --install-external
is passed; a plain `python install.py` run never installs or updates them.
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


# Third-party plugins (not part of this project) that can optionally be
# installed/updated alongside this repo's own plugins, via --install-external.
# Keyed by the directory name they're cloned into under the BN plugin folder.
EXTERNAL_PLUGINS = {
    "blob_extractor": ("Blob Extractor", "https://github.com/Vector35/blob_extractor"),
    "kaitai": ("Kaitai UI Plugin", "https://github.com/Vector35/kaitai"),
    "snippets": ("Snippets UI Plugin", "https://github.com/Vector35/snippets"),
    "tanto": ("Tanto", "https://github.com/Vector35/tanto"),
}


def install_requirements(dest, req_file):
    """Pip-install req_file's dependencies into dest/.deps, if req_file exists."""
    if not req_file.exists():
        return
    deps_dir = dest / ".deps"
    if deps_dir.exists():
        shutil.rmtree(deps_dir)
    deps_dir.mkdir(exist_ok=True)
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "--no-warn-conflicts", "-t", str(deps_dir), "-r", str(req_file)],
        check=True,
    )
    print(f"  deps installed -> {deps_dir}")


def install_external_plugin(dest_name, display_name, url, bn_plugin_dir):
    dest = bn_plugin_dir / dest_name
    if dest.exists():
        if (dest / ".git").is_dir():
            subprocess.run(["git", "-C", str(dest), "pull", "--ff-only"], check=True)
            print(f"  updated {display_name} -> {dest}")
            install_requirements(dest, dest / "requirements.txt")
        else:
            print(
                f"  skipped {display_name}: {dest} already exists and isn't a git "
                "checkout -- remove it manually first if you want it managed here"
            )
        return

    subprocess.run(["git", "clone", url, str(dest)], check=True)
    print(f"  cloned {display_name} -> {dest}")

    install_requirements(dest, dest / "requirements.txt")


def install_external_plugins(bn_plugin_dir):
    print(f"\nInstalling {len(EXTERNAL_PLUGINS)} third-party plugin(s) to {bn_plugin_dir}:\n")
    for dest_name, (display_name, url) in EXTERNAL_PLUGINS.items():
        install_external_plugin(dest_name, display_name, url, bn_plugin_dir)


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

    install_requirements(dest, plugin_path / "requirements.txt")


def main():
    parser = argparse.ArgumentParser(description="Install Binary Ninja plugins")
    parser.add_argument("--link", action="store_true", help="Symlink plugins (dev mode)")
    parser.add_argument("--interactive", action="store_true", help="Interactive selection prompt")
    parser.add_argument("--plugin-dir", type=Path, help="Override BN plugin folder")
    parser.add_argument(
        "--install-external",
        action="store_true",
        help="Also install/update third-party plugins (Blob Extractor, Kaitai, Snippets, Tanto) "
        "as plain git clones; unaffected by --link",
    )
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

    if args.install_external:
        install_external_plugins(bn_plugin_dir)

    print("\nDone.")


if __name__ == "__main__":
    main()
