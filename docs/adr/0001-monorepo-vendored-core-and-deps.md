# Monorepo with per-plugin vendored `core/` and deps

Each plugin ships as a self-contained install tree: its own source, its own
vendored copy of `core/`, and its own `.deps/` directory of pinned third-party
packages. This sacrifices sharing to guarantee that any single plugin can be
updated (langchain bump, `core/` API change) without touching the others — a
property we value more than deduplication for reverse-engineering tooling that
evolves plugin-by-plugin.