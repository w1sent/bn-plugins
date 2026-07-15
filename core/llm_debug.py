"""Shared LLM request debug logging, opt-in per plugin via a
`<plugin>.debug_logging` BN setting. When enabled, every LLM request a
plugin makes -- including each internal call a multi-step (deepagents)
agent session makes across its own tool-calling steps, not just the first
one -- is appended to ~/.binaryninja/llm-request.log with a timestamp and
which plugin triggered it, so prompt/response issues can be diagnosed
without instrumenting each call site by hand.
"""

import datetime
from pathlib import Path

_LOG_PATH = Path.home() / ".binaryninja" / "llm-request.log"


def is_enabled(setting_key, bv=None):
    from binaryninja import Settings

    return Settings().get_bool(setting_key, resource=bv)


def _write(plugin_name, provider_config, label, content):
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().isoformat(timespec="seconds")
        model = (provider_config or {}).get("model", "unknown")
        provider_type = (provider_config or {}).get("type", "unknown")
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(
                f"[{timestamp}] plugin={plugin_name} provider={provider_type} "
                f"model={model} {label}\n"
            )
            f.write(str(content).rstrip("\n"))
            f.write("\n---\n")
    except OSError:
        pass  # best-effort -- a logging failure must never break a suggestion


def log_request(plugin_name, provider_config, prompt):
    """Log a single-shot (non-agentic) LLM request directly -- e.g. single
    mode's one-shot `llm.invoke(prompt)`."""
    _write(plugin_name, provider_config, "request", prompt)


def make_callback(plugin_name, provider_config):
    """A LangChain callback handler that logs every LLM call made during a
    run -- including each internal call inside a multi-step LangGraph/
    deepagents session, which a single log_request() call before `.invoke()`
    would miss, since the agent may call the model many times per session.
    Pass it via `config={"callbacks": [...]}` to `.invoke()`.

    Returns None if langchain_core isn't importable (deps not on sys.path
    yet) rather than raising -- callers should skip adding callbacks in
    that case instead of failing the whole request over a logging feature.
    """
    try:
        from langchain_core.callbacks import BaseCallbackHandler
    except ImportError:
        return None

    class _DebugLogCallback(BaseCallbackHandler):
        def on_llm_start(self, serialized, prompts, **kwargs):
            for p in prompts:
                _write(plugin_name, provider_config, "request (llm)", p)

        def on_chat_model_start(self, serialized, messages, **kwargs):
            for message_list in messages:
                rendered = "\n".join(f"{m.type}: {m.content}" for m in message_list)
                _write(plugin_name, provider_config, "request (chat)", rendered)

    return _DebugLogCallback()
