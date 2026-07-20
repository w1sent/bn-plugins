# Minimize modal interruption: log over popups for anything not blocking on required input

Plugin UI choices carry a flow cost: a modal popup (`show_message_box`) stops
the reverse engineer and demands a dismissal click before they can continue,
even for a routine success count or an expected "nothing to do here." That
cost is worth paying only when the operation genuinely cannot proceed
without an answer from the user right now (e.g. `get_choice_input`,
`get_text_line_input`, `get_int_input` gathering a required parameter).
Status, results, and error reporting for a completed or aborted operation
are not that case — the user isn't blocked, so log to BN's console (per
ADR-0012) instead, generalizing ADR-0024's "prefer BN-native display" and
ADR-0025's "log + tags" into an explicit rule: passive feedback (log, tags,
status bar) over synchronous modal interruption whenever the user isn't
actually blocked on providing input.

Applied to `ai/auto-rename`: `show_message_box` calls for success/failure
summaries, "no functions found," "invalid regex," and ordering errors become
`logger` calls; the three genuine input prompts are unchanged.
