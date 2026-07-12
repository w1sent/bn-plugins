# AI agents run on background tasks, DB writes on main thread

AI plugin agents (langchain/deepagents) execute on Binary Ninja's built-in
background task/thread mechanism so the GUI stays responsive during LLM
calls that may take seconds to minutes. When the agent produces results, DB
mutations are dispatched to the main thread via BN's
`execute_on_main_thread` to avoid thread-safety issues with the BN API.

Rejected: synchronous blocking on the main thread (freezes the UI),
out-of-process agent with IPC (unnecessary complexity for this scale).