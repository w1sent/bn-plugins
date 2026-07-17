"""MCP prompts: pre-built templates for common RE tasks (see TODO.md phase
5). Always registered -- prompts are just message templates for an AI client
to send itself, not tool calls with side effects, so there's no gating
setting for them.
"""


def analyze_function(addr: str) -> str:
    """Analyze a specific function and explain what it does."""
    return (
        f"Analyze the function at {addr} in the currently open binary and explain what it does. "
        "Use get_function to read its disassembly/HLIL, get_xrefs_to/get_xrefs_from to understand "
        "callers and callees, and get_strings/get_data for any referenced constants. Summarize the "
        "function's purpose, inputs, outputs, and any notable logic or side effects."
    )


def find_crypto() -> str:
    """Find cryptographic routines in this binary."""
    return (
        "Find cryptographic routines in the currently open binary. Look for telltale constants "
        "(e.g. AES S-boxes, SHA/MD5 initialization values, CRC polynomials), imported crypto library "
        "symbols, and functions with the characteristic loop/permutation structure of block ciphers "
        "or hash functions. Use search and get_strings to look for crypto-related names, get_symbols "
        "and get_imports for library calls, and get_function to inspect candidate functions' logic. "
        "Report each candidate routine's address, likely algorithm, and your reasoning."
    )


def suggest_names() -> str:
    """Suggest meaningful names for unnamed functions."""
    return (
        "Suggest meaningful names for unnamed functions (e.g. sub_XXXXXX) in the currently open "
        "binary. Use get_functions to list them, get_function to inspect each one's disassembly/HLIL "
        "and get_xrefs_to/get_xrefs_from for callers/callees to infer purpose, then propose a "
        "descriptive name for each and use rename_function to apply it once you're confident."
    )


def reverse_engineering() -> str:
    """Help me reverse engineer this binary."""
    return (
        "Help me reverse engineer the currently open binary. Start with binary://metadata and "
        "get_functions/get_symbols/get_strings/get_imports/get_exports to get an overview, identify "
        "the entry point and main logic, then dig into interesting functions with get_function. "
        "Explain the binary's overall purpose and structure as you go."
    )


_PROMPTS = (
    (analyze_function, "analyze-function"),
    (find_crypto, "find-crypto"),
    (suggest_names, "suggest-names"),
    (reverse_engineering, "reverse-engineering"),
)


def register(mcp) -> None:
    for fn, name in _PROMPTS:
        mcp.prompt(name=name, description=fn.__doc__)(fn)
