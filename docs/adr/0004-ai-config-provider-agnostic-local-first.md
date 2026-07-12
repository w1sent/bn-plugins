# Provider-agnostic AI config, local-first, keyless

AI plugins read a shared `~/.binaryninja/ai-config.json` that declares
available providers (Ollama, OpenAI, Anthropic, etc.) with per-provider
parameters and a `default` provider. The config stores no API keys — plugins
read each provider's standard env var (`OPENAI_API_KEY`, etc.) at runtime.
Defaults to Ollama at `localhost:11434` if no config file exists, so the
plugins work out of the box with a local model and no network dependency.

Rejected: storing API keys in the config file (security risk), cloud-first
default (breaks air-gapped RE workflows).