# Two installer modes: `--copy` (default) and `--link` (dev)

The installer materializes plugins either by copying (`--copy`, default for
end users) or by symlinking (`--link`, for development).

In `--copy` mode, the plugin directory and `core/` are both real copies
under BN's plugin folder (`shutil.copytree`), fully self-contained per
ADR-0001.

In `--link` mode, `dest` (the plugin's directory under BN's plugin folder)
is a real directory, not a symlink — the installer creates it and then
symlinks each file/dir from the plugin's source into it individually,
plus a `core` symlink pointing at the monorepo's shared `core/`. This
keeps editing in-place (edits to the repo are picked up immediately, no
reinstall) while still giving every plugin its own `core` entry, matching
`--copy` mode's layout. `.deps/` is excluded from the per-entry symlink
step and always installed fresh into `dest/.deps` for both modes, so the
runtime finds langchain etc.

Earlier, `--link` mode symlinked the *entire* plugin directory as one
unit (`os.symlink(plugin_path, dest)`). This was wrong: `dest` was then
literally the same directory as the repo's plugin source, so it never
got its own `core/`, and anything the installer wrote under `dest` (a
`core` symlink, `.deps/`) actually landed back in the repo's source tree
through the symlink. Per-entry symlinking with a real `dest` directory
fixes both problems. See `docs/common-issues.md` for the symptom this
produced.