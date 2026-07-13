from .ai_config import load_ai_config, resolve_provider
from .background import run_background_task
from .bn_context import (
    get_call_graph,
    get_data_references,
    get_function_context,
    get_symbol_table,
)
from .config_file import load_or_create_json_config
from .exceptions import AIConfigError, AITimeoutError, PluginError
from .logging import get_logger, set_log_level
from .prompts import clear_prompt_cache, load_prompt
from .retry import retry_with_backoff

__version__ = "0.1.0"


def register_setting(key, description, default, scope="user"):
    from .settings import register_setting as _register
    return _register(key, description, default, scope)


def create_tag_type(bv, name, icon=""):
    from .tags import create_tag_type as _create
    return _create(bv, name, icon)


def tag_item(bv, addr, tag_type_name, data=""):
    from .tags import tag_item as _tag
    return _tag(bv, addr, tag_type_name, data)
