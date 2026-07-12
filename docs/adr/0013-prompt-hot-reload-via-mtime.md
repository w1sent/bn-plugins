# Prompt hot-reload via mtime check

`core/`'s `load_prompt()` caches prompt content and file mtime. On each call
it stats the file and re-reads if the mtime changed. This means editing a
prompt file and re-running the plugin command picks up the new prompt
without restarting Binary Ninja. The overhead is one stat per prompt per
command invocation — negligible.