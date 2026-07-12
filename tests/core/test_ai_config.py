import json
import os
import tempfile
from pathlib import Path

from core.ai_config import load_ai_config, resolve_provider
from core.exceptions import AIConfigError


def test_loads_default_config_when_no_file():
    config = load_ai_config("/nonexistent/path/ai-config.json")
    assert config["default"] == "local"
    assert "local" in config["providers"]
    assert config["providers"]["local"]["type"] == "ollama"


def test_merges_user_config_with_defaults():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ai-config.json"
        path.write_text(json.dumps({
            "default": "custom",
            "providers": {
                "custom": {
                    "type": "openai",
                    "model": "gpt-4o",
                }
            },
            "parameters": {"temperature": 0.5},
        }))
        config = load_ai_config(path)
        assert config["default"] == "custom"
        assert config["providers"]["custom"]["type"] == "openai"
        assert config["providers"]["custom"]["model"] == "gpt-4o"
        assert config["parameters"]["temperature"] == 0.5
        assert config["parameters"]["max_tokens"] == 4096


def test_merges_provider_params_with_global():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ai-config.json"
        path.write_text(json.dumps({
            "providers": {
                "local": {
                    "type": "ollama",
                    "model": "llama3.1:8b",
                    "parameters": {"temperature": 0.0},
                }
            },
            "parameters": {"temperature": 0.1, "max_tokens": 2048},
        }))
        config = load_ai_config(path)
        provider = config["providers"]["local"]
        assert provider["parameters"]["temperature"] == 0.0
        assert provider["parameters"]["max_tokens"] == 2048


def test_resolve_provider_uses_default():
    config = {
        "default": "local",
        "providers": {
            "local": {"type": "ollama", "model": "llama3.1:8b"}
        },
        "parameters": {"temperature": 0.1},
    }
    resolved = resolve_provider(config)
    assert resolved["type"] == "ollama"
    assert resolved["model"] == "llama3.1:8b"


def test_resolve_provider_by_name():
    config = {
        "default": "local",
        "providers": {
            "local": {"type": "ollama", "model": "llama3.1:8b"},
            "cloud": {"type": "openai", "model": "gpt-4o"},
        },
        "parameters": {"temperature": 0.1},
    }
    resolved = resolve_provider(config, "cloud")
    assert resolved["type"] == "openai"
    assert resolved["model"] == "gpt-4o"


def test_resolve_provider_raises_on_missing():
    config = {"default": "local", "providers": {}, "parameters": {}}
    try:
        resolve_provider(config)
        assert False, "expected AIConfigError"
    except AIConfigError:
        pass


def test_resolve_provider_merges_params():
    config = {
        "default": "local",
        "providers": {
            "local": {
                "type": "ollama",
                "model": "llama3.1:8b",
                "parameters": {"temperature": 0.0},
            }
        },
        "parameters": {"temperature": 0.1, "max_tokens": 4096},
    }
    resolved = resolve_provider(config)
    assert resolved["parameters"]["temperature"] == 0.0
    assert resolved["parameters"]["max_tokens"] == 4096


def test_resolve_provider_reads_env_var(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test123")
    config = {
        "default": "cloud",
        "providers": {
            "cloud": {"type": "openai", "model": "gpt-4o"}
        },
        "parameters": {},
    }
    resolved = resolve_provider(config)
    assert resolved["api_key"] == "sk-test123"


def test_resolve_provider_skips_env_var_when_not_set():
    os.environ.pop("OPENAI_API_KEY", None)
    config = {
        "default": "cloud",
        "providers": {
            "cloud": {"type": "openai", "model": "gpt-4o"}
        },
        "parameters": {},
    }
    resolved = resolve_provider(config)
    assert "api_key" not in resolved
