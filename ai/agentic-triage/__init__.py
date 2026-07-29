import sys
from pathlib import Path

_plugin_dir = Path(__file__).parent.resolve()
_deps = _plugin_dir / ".deps"
if _deps.is_dir() and str(_deps) not in sys.path:
    sys.path.insert(0, str(_deps))

from .core.logging import get_logger
from .core.settings import register_setting

from . import widget

logger = get_logger("agentic_triage")

register_setting(
    "agentic_triage.provider",
    "Provider name from ai-config.json (empty = default)",
    "",
)
register_setting(
    "agentic_triage.max_summary_tokens",
    "Approximate word budget for the AI-enhancer summary (quick and full analysis both enforce this)",
    400,
)
register_setting(
    "agentic_triage.agent_max_steps",
    "Tool-call budget per full-analysis (agent) session",
    80,
)
register_setting(
    "agentic_triage.debug_logging",
    "Log every LLM request (timestamp, plugin, provider/model, prompt) to ~/.binaryninja/llm-request.log",
    False,
)

widget.register_view_type()

logger.info("agentic-triage loaded")
