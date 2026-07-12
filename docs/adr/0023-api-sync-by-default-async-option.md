# API calls: sync by default, async via `async_run=True`

API functions are synchronous by default — `result = api.rename_function(bv,
func)` blocks until the LLM responds. For batch operations or slow models,
`async_run=True` returns a `Future`-like object with `.result()`, `.done()`,
and `.cancel()`. The `PluginCommand` wrapper always uses async mode so the
BN UI stays responsive.