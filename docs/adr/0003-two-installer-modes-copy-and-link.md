# Two installer modes: `--copy` (default) and `--link` (dev)

The installer materializes plugins either by copying (`--copy`, default for
end users) or by symlinking (`--link`, for development). In `--link` mode the
monorepo's single `core/` is symlinked into BN's plugin folder as a sibling
of the plugin, so the editor workspace root resolves `from core import ...`
natively and LSP/linting works without extra config; `.deps/` is still
populated in-tree so the runtime finds langchain etc. The production "vendor
`core/` per plugin" rule applies only to `--copy` installs; dev uses one
shared symlinked `core/` to keep edits and LSP clean.