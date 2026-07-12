# langchain for single-step, deepagents for multi-step AI tasks

AI plugins use langchain directly for single-step tasks (summarize a
function, suggest a name) and deepagents for multi-step compound tasks
(analyze a binary, trace data flow, create structs). Plugins that could
work either way expose a toggle or offer both modes as separate commands so
the user chooses the complexity/quality trade-off.

Rejected: deepagents for everything (overkill for simple tasks, heavier
dep), langchain for everything (no planning/reflection for compound tasks).