# Auto-create complex config files with defaults on first use

Per ADR-0015, each plugin's complex config (provider-agnostic bits like
custom prompts, temperature, retry backoff steps) lives in a JSON file
whose path is itself a BN Setting (`<plugin>.config_path`). Until now that
setting was registered but nothing ever read the file it pointed at, so it
was effectively dead — there was no discoverable, editable place for these
values, and no way to know the expected shape without reading source.

The fix is a general-purpose rule, not an auto-rename-specific one:
**the first time a plugin needs its complex config, and no file exists at
`config_path`, write one populated with the plugin's default values, then
proceed using those defaults.** `core.load_or_create_json_config(path,
defaults)` implements this: create-with-defaults if missing, otherwise load
and shallow-merge on top of defaults (so an old config file gains new
default keys automatically instead of silently missing them).

This makes the config file self-documenting — a user who wants to change
`temperature` or add a `custom_prompt` opens the file BN's Settings dialog
already points them at and finds every key with a sane starting value,
instead of an empty or absent file. Every future AI plugin with a complex
config should use `load_or_create_json_config` the same way rather than
hand-rolling its own load path, so this behavior stays consistent across
the AI bucket.
