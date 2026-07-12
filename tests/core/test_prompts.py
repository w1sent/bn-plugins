import tempfile
from pathlib import Path

from core.prompts import load_prompt, clear_prompt_cache


def test_loads_prompt_from_file():
    with tempfile.TemporaryDirectory() as tmp:
        plugin_dir = Path(tmp)
        prompts_dir = plugin_dir / "prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "rename.txt"
        prompt_file.write_text("Rename the function {name}")

        result = load_prompt(plugin_dir, "rename.txt")
        assert result == "Rename the function {name}"


def test_raises_on_missing_prompt():
    try:
        load_prompt("/nonexistent", "missing.txt")
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass


def test_caches_prompt_content():
    clear_prompt_cache()
    with tempfile.TemporaryDirectory() as tmp:
        plugin_dir = Path(tmp)
        prompts_dir = plugin_dir / "prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "test.txt"
        prompt_file.write_text("version 1")

        result1 = load_prompt(plugin_dir, "test.txt")
        result2 = load_prompt(plugin_dir, "test.txt")
        assert result1 == "version 1"
        assert result2 == "version 1"


def test_hot_reload_on_mtime_change():
    clear_prompt_cache()
    with tempfile.TemporaryDirectory() as tmp:
        plugin_dir = Path(tmp)
        prompts_dir = plugin_dir / "prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "test.txt"
        prompt_file.write_text("version 1")

        result1 = load_prompt(plugin_dir, "test.txt")
        assert result1 == "version 1"

        prompt_file.write_text("version 2")
        result2 = load_prompt(plugin_dir, "test.txt")
        assert result2 == "version 2"


def test_clear_cache():
    clear_prompt_cache()
    with tempfile.TemporaryDirectory() as tmp:
        plugin_dir = Path(tmp)
        prompts_dir = plugin_dir / "prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "test.txt"
        prompt_file.write_text("content")

        load_prompt(plugin_dir, "test.txt")
        clear_prompt_cache()
        prompt_file.write_text("new content")
        result = load_prompt(plugin_dir, "test.txt")
        assert result == "new content"
