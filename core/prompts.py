from pathlib import Path

_cache = {}


def load_prompt(plugin_dir, name):
    prompt_path = Path(plugin_dir) / "prompts" / name
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

    key = str(prompt_path)
    mtime = prompt_path.stat().st_mtime
    if key in _cache and _cache[key][0] == mtime:
        return _cache[key][1]

    content = prompt_path.read_text()
    _cache[key] = (mtime, content)
    return content


def clear_prompt_cache():
    _cache.clear()
