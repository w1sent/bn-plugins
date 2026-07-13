import json
import os
from pathlib import Path

from .config_file import create_json_file_if_missing
from .exceptions import AIConfigError

DEFAULT_CONFIG_PATH = Path.home() / ".binaryninja" / "ai-config.json"

DEFAULT_CONFIG = {
    "default": "local",
    "providers": {
        "local": {
            "type": "ollama",
            "model": "llama3.1:8b",
            "endpoint": "http://localhost:11434",
        }
    },
    "parameters": {
        "temperature": 0.1,
        "max_tokens": 4096,
    },
}

_PROVIDER_ENV_VARS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
    "together": "TOGETHER_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "cohere": "COHERE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}


def load_ai_config(path=None):
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    if create_json_file_if_missing(path, DEFAULT_CONFIG):
        return json.loads(json.dumps(DEFAULT_CONFIG))

    with open(path) as f:
        user_config = json.load(f)

    config = json.loads(json.dumps(DEFAULT_CONFIG))
    config["default"] = user_config.get("default", config["default"])
    config["parameters"].update(user_config.get("parameters", {}))

    for name, provider in user_config.get("providers", {}).items():
        if name not in config["providers"]:
            config["providers"][name] = provider
        else:
            config["providers"][name].update(provider)
        merged_params = dict(config["parameters"])
        merged_params.update(provider.get("parameters", {}))
        config["providers"][name]["parameters"] = merged_params

    return config


def resolve_provider(config, provider_name=None):
    name = provider_name or config.get("default", "local")
    provider = config.get("providers", {}).get(name)
    if not provider:
        raise AIConfigError(f"Provider '{name}' not found in ai-config.json")

    resolved = dict(provider)
    provider_type = resolved.get("type", "").lower()
    env_var = _PROVIDER_ENV_VARS.get(provider_type)
    if env_var:
        api_key = os.environ.get(env_var)
        if api_key:
            resolved["api_key"] = api_key

    global_params = config.get("parameters", {})
    provider_params = resolved.get("parameters", {})
    merged_params = dict(global_params)
    merged_params.update(provider_params)
    resolved["parameters"] = merged_params

    return resolved
