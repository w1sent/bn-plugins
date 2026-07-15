"""Multi-mode (deepagents) struct-suggestion agent.

Local to suggest-structs -- this is the repo's first deepagents consumer,
so the agent-building boilerplate stays here rather than in shared core/
until a second plugin needs it (see TODO.md / design-session notes).

Unlike single mode (one LLM call producing unapplied preview text), the
multi-mode agent mutates the BinaryView live during its session via tools,
wrapped by the caller in one BN undo boundary. The session is only
considered successful if the agent calls `confirm_edits`; otherwise the
caller must not commit the undo actions (full rollback on cancel/failure,
see TODO.md "Modes").
"""

import string
import sys
from pathlib import Path
from typing import Optional

from .core.logging import get_logger
from .core.tags import tag_item
from .api import (
    SkeletonField,
    _build_var_context,
    _skeleton_to_text,
    extract_skeleton,
    _hlil_var_for,
)

_plugin_dir = Path(__file__).parent.resolve()
logger = get_logger("suggest_structs")


def _ensure_deps_on_path():
    deps = _plugin_dir / ".deps"
    if deps.is_dir() and str(deps) not in sys.path:
        sys.path.insert(0, str(deps))


def _build_agent_llm(provider_config):
    _ensure_deps_on_path()
    provider_type = provider_config.get("type", "").lower()
    params = provider_config.get("parameters", {})

    if provider_type == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=provider_config.get("model", "llama3.1:8b"),
            base_url=provider_config.get("endpoint", "http://localhost:11434"),
            temperature=params.get("temperature", 0.1),
            num_predict=params.get("max_tokens", 4096),
        )

    if provider_type == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=provider_config.get("model", "claude-3-5-sonnet-latest"),
            api_key=provider_config.get("api_key"),
            temperature=params.get("temperature", 0.1),
            max_tokens=params.get("max_tokens", 4096),
        )

    if provider_type == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=provider_config.get("model", "gemini-2.0-flash"),
            api_key=provider_config.get("api_key"),
            temperature=params.get("temperature", 0.1),
        )

    from langchain_openai import ChatOpenAI

    kwargs = {
        "model": provider_config.get("model", "gpt-4o"),
        "temperature": params.get("temperature", 0.1),
        "max_tokens": params.get("max_tokens", 4096),
    }
    api_key = provider_config.get("api_key")
    if api_key:
        kwargs["api_key"] = api_key
    endpoint = provider_config.get("endpoint")
    if endpoint:
        kwargs["base_url"] = endpoint
    return ChatOpenAI(**kwargs)


class _SessionState:
    """Mutable state shared by the tool closures for one agent session."""

    def __init__(self, bv, func, tag_type_name):
        self.bv = bv
        self.func = func
        self.tag_type_name = tag_type_name
        self.structs = {}       # name -> c_definition text
        self.applied = []       # list of (var_name, struct_name)
        self.confirmed = False
        self.error = None


def _build_tools(state, max_structs):
    from langchain_core.tools import tool

    bv = state.bv

    @tool
    def get_variable_context(address: int, var_name: str) -> str:
        """Get the deterministic access-pattern skeleton and surrounding
        HLIL/string/data context for a variable in the function containing
        `address`. Use this to investigate nested or related pointers
        before proposing a struct for them."""
        funcs = bv.get_functions_containing(address)
        if not funcs:
            return f"error: no function contains address {address:#x}"
        func = funcs[0]
        var = _hlil_var_for(func, var_name)
        if var is None:
            return f"error: no HLIL variable named {var_name!r} in function at {func.start:#x}"
        skeleton = extract_skeleton(bv, func, var)
        ctx = _build_var_context(bv, func, var, skeleton)
        return (
            f"function: {ctx['function_name']} ({ctx['address']})\n"
            f"variable: {ctx['var_name']}\n"
            f"skeleton:\n{ctx['skeleton']}\n"
            f"string_refs:\n{ctx['string_refs']}\n"
            f"data_refs:\n{ctx['data_refs']}\n"
            f"existing_types:\n{ctx['existing_types']}\n"
            f"disassembly:\n{ctx['disassembly']}"
        )

    @tool
    def lookup_type(name: str) -> str:
        """Return the exact C definition of an existing user-defined type
        named `name`, so you can check whether it already matches the
        struct you're about to propose instead of redefining it."""
        t = bv.get_type_by_name(name)
        if t is None:
            return f"error: no type named {name!r} exists"
        return f"struct {name} {t}"

    @tool
    def list_type_names(prefix: Optional[str] = None) -> str:
        """List existing user-defined type names, optionally filtered by
        `prefix`, so you can discover reuse candidates cheaply without
        pulling every type's full definition into context."""
        names = list(bv.type_names)
        if prefix:
            names = [n for n in names if str(n).startswith(prefix)]
        return "\n".join(str(n) for n in names[:200]) or "(none)"

    @tool
    def submit_struct(name: str, c_definition: str) -> str:
        """Register a struct definition under `name` for this session.
        Callable multiple times (once per struct, including nested ones
        discovered via get_variable_context). Does not apply it to any
        variable -- call apply_struct separately for that."""
        if len(state.structs) >= max_structs and name not in state.structs:
            return f"error: session cap of {max_structs} structs reached"
        state.structs[name] = c_definition
        return f"registered struct {name}"

    @tool
    def undo_struct(name: str) -> str:
        """Retract a struct submitted earlier this session (e.g. if you
        realize the layout was wrong). Does not undo apply_struct calls
        already made with it -- reapply after resubmitting if needed."""
        if name not in state.structs:
            return f"error: no struct named {name!r} was submitted this session"
        del state.structs[name]
        return f"retracted struct {name}"

    @tool
    def apply_struct(address: int, var_name: str, struct_name: str) -> str:
        """Apply a struct submitted this session to the pointer variable
        `var_name` in the function containing `address`. Mutates the
        binary immediately (wrapped in the caller's undo boundary)."""
        if struct_name not in state.structs:
            return f"error: struct {struct_name!r} was not submitted this session"
        funcs = bv.get_functions_containing(address)
        if not funcs:
            return f"error: no function contains address {address:#x}"
        func = funcs[0]
        var = _hlil_var_for(func, var_name)
        if var is None:
            return f"error: no HLIL variable named {var_name!r} in function at {func.start:#x}"
        try:
            parsed = bv.parse_types_from_string(state.structs[struct_name])
            for n, t in parsed.types.items():
                if n not in set(bv.type_names):
                    bv.define_user_type(n, t)
            ptr_type = bv.parse_type_string(f"struct {struct_name}*")[0]
            func.create_user_var(var, ptr_type, var.name)
        except Exception as e:
            return f"error: failed to apply struct {struct_name} to {var_name}: {e}"
        state.applied.append((var_name, struct_name))
        if state.tag_type_name:
            tag_item(bv, func.start, state.tag_type_name, f"applied struct {struct_name} to {var_name}")
        return f"applied struct {struct_name} to {var_name} at {func.start:#x}"

    @tool
    def confirm_edits() -> str:
        """Signal that this struct-suggestion session is complete. Required
        for the session to be treated as successful -- a session that ends
        without calling this is a failure and every edit made is rolled
        back by the caller."""
        state.confirmed = True
        return "session confirmed"

    return [
        get_variable_context,
        lookup_type,
        list_type_names,
        submit_struct,
        undo_struct,
        apply_struct,
        confirm_edits,
    ]


def run_agent_session(
    bv, func, var, skeleton, *, provider_config, custom_prompt,
    max_steps, max_structs, tag_type_name,
):
    """Run one multi-mode agent session targeting `var` (or a range seed
    when `var` is None, per `skeleton`). Mutates `bv` live via tools.

    Returns (definition_text, applied_struct_names, error). `error` is set
    (and the caller must not commit its undo boundary) if the agent never
    calls confirm_edits -- see module docstring.
    """
    from .core.prompts import load_prompt

    _ensure_deps_on_path()
    from deepagents import create_deep_agent
    from langgraph.errors import GraphRecursionError

    state = _SessionState(bv, func, tag_type_name)
    tools = _build_tools(state, max_structs)
    llm = _build_agent_llm(provider_config)

    system_prompt = custom_prompt or load_prompt(_plugin_dir, "agent_system.txt")
    ctx = _build_var_context(bv, func, var, skeleton)
    task = string.Template(load_prompt(_plugin_dir, "agent_task.txt")).safe_substitute(ctx)

    agent = create_deep_agent(model=llm, tools=tools, system_prompt=system_prompt)

    # The agent's apply_struct tool mutates bv live; wrap the whole session
    # in one undo boundary and only commit on confirm_edits -- any other
    # outcome (step budget exceeded, exception, no confirm_edits) reverts
    # every edit the agent made this session (full rollback, see TODO.md).
    undo_id = bv.begin_undo_actions()
    error = None
    try:
        agent.invoke(
            {"messages": [{"role": "user", "content": task}]},
            config={"recursion_limit": max_steps * 2},
        )
    except GraphRecursionError:
        error = f"agent exceeded step budget ({max_steps}) without calling confirm_edits"
    except Exception as e:
        logger.error(f"agent session failed for {var.name if var else '(range)'} at {func.start:#x}: {e}")
        error = str(e)

    if error is None and not state.confirmed:
        error = "agent session ended without calling confirm_edits"

    if error is not None:
        bv.revert_undo_actions(undo_id)
        return None, [], error

    bv.commit_undo_actions(undo_id)
    definition = "\n\n".join(state.structs.values())
    applied_names = [struct_name for _var_name, struct_name in state.applied]
    return definition, applied_names, None
