# Common Issues

Gotchas that cost real debugging time. Check here before re-diagnosing from
scratch.

## `ModuleNotFoundError: No module named 'core'` when a plugin loads in BN

**Symptom:** Plugin fails to load with a traceback pointing at
`from core.X import Y` in `__init__.py` or another top-level plugin module,
even though `core/` is clearly vendored inside the installed plugin
directory.

**Cause:** `from core.X import Y` is an *absolute* import. It only resolves
if the plugin's own install directory is itself on `sys.path` — not just
its parent (`~/.binaryninja/plugins`). That's only guaranteed for plugins
loaded through BN's repo-tracked Plugin Manager path; for plugins dropped
into the user plugin folder by `scripts/install.py`, only the parent folder
is reliably on `sys.path`.

**Fix:** Import vendored `core/` as a relative submodule of the plugin's
own package: `from .core.X import Y`, not `from core.X import Y`. This
resolves via `__package__`/`__path__` and doesn't depend on `sys.path` at
all. See `ai/auto-rename/__init__.py` and `api.py`.

## `install.py --link` leaves plugins without `core/`, or pollutes the repo source tree

**Symptom:** `--link`-installed plugins fail to import `core` even after
copy-mode installs work fine; or stray `.deps/` / `core` entries appear as
untracked files inside the repo's own plugin directories.

**Cause:** An earlier version of `install.py`'s link mode symlinked the
*entire* plugin directory into BN's plugin folder (`os.symlink(plugin_path,
dest)`). That means `dest` was literally the same directory as the repo's
`ai/<plugin>/` — so `dest` never got its own `core/` subdir, and any code
that wrote into `dest/whatever` (a `core` symlink, a `.deps` pip target)
actually wrote into the repo source tree through the symlink.

**Fix:** Link mode now creates a real directory at `dest` and symlinks each
plugin file/dir into it individually (still edit-in-place), plus a separate
`core` symlink to the shared library. `.deps/` is skipped when linking
individual entries and always installed fresh per plugin. If you find a
stray `.deps/` or `core` directory sitting inside a plugin's source folder
in the repo (not the BN plugin install location), it's leftover pollution
from the old bug — safe to delete, it should be gitignored.

## `pip install -t .deps` prints a scary `ERROR: ... dependency resolver`

**Symptom:**
```
ERROR: pip's dependency resolver does not currently take into account all the packages that are installed.
frida-tools 14.8.2 requires websockets<14.0.0,>=13.0.0, but you have websockets 15.0.1 which is incompatible.
```
during `install.py`, even though the install completes successfully
(`Successfully installed ...` prints right after, exit code 0).

**Cause:** `pip install -t <dir>` cross-checks new packages against
*everything already installed in the ambient Python environment* for
conflicts, even though `-t` installs to an isolated target directory
unrelated to that environment. An unrelated globally-installed tool
(`frida-tools` pinning an old `websockets`) trips the check.

**Fix:** `install.py` passes `--no-warn-conflicts` to pip for the `.deps/`
install step. If you see this warning elsewhere, it's almost always noise
for `-t`-targeted installs — check the command still reports
`Successfully installed` and exits 0 before treating it as a real failure.

## `pytest` fails to collect tests under a plugin's `tests/` dir with a `binaryninja` import error

**Symptom:** Running `python3 -m pytest ai/<plugin>/tests/test_X.py` from
the plugin root (or repo root) fails for *every* test with
`ModuleNotFoundError: No module named 'binaryninja'` (or `core`), during
test **setup**, not collection — even for pure, BN-independent test files.

**Cause:** pytest treats any ancestor directory containing `__init__.py` as
a `Package` collector, and imports it as a real Python module during setup.
Since `ai/<plugin>/__init__.py` imports `binaryninja`/`core` (only
available inside BN), pytest fails constructing the `Package` node for the
plugin directory before your actual test file ever runs — regardless of
`--import-mode`.

**Fix:** Run pytest with your working directory *inside* `tests/` itself:
```
cd ai/<plugin>/tests && python3 -m pytest test_X.py
```
This avoids pytest walking up to the plugin root and treating it as a
Package. Don't try to fix this by editing the plugin's `__init__.py`
import structure — that's the normal, correct shape for a BN plugin, per
ADR-0009.

## `core.register_setting()` raises `TypeError: register_setting() got an unexpected keyword argument`

**Symptom:** Plugin import fails inside `core/settings.py` when calling the
real `binaryninja.Settings.register_setting`, e.g.
`TypeError: Settings.register_setting() got an unexpected keyword argument 'scope'`.

**Cause:** The real BN API is
`Settings.register_setting(self, key: str, properties: str) -> bool`, where
`properties` is a single JSON string with required `"title"`/`"type"`/
`"description"` keys (plus optional `"default"` etc.) — not
`(key, description, default, scope=...)`. `core/settings.py` was written
against an assumed signature that didn't match, so every call from any
plugin's `register_setting(...)` blew up at import time.

**Fix:** `core/settings.py` now builds the JSON schema string itself,
inferring `"type"` from the Python type of `default` (`bool` → `"boolean"`,
`int`/`float` → `"number"`, else `"string"`) and a `"title"` from the key's
last dot-segment. If you add a new call to `core.register_setting`, you
only need to pass `key, description, default` — don't assume BN's
lower-level `Settings.register_setting` takes those directly.

## `AttributeError: type object 'PluginCommand' has no attribute 'register_for_selection'`, or `BinaryView` has no `get_current_function`/`get_selected_functions`

**Symptom:** Plugin import fails with `AttributeError` pointing at
`PluginCommand.register_for_selection(...)`, or (if that's worked around)
a later `AttributeError`/crash from `bv.get_current_function()` or
`bv.get_selected_functions()` inside a command handler.

**Cause:** These methods don't exist in the real BN API — they were
invented based on what would be convenient, not checked against
`binaryninja/plugin.py` and `binaryninja/binaryview.py`. The real
`PluginCommand` only has `register`, `register_for_address`,
`register_for_range`, `register_for_function`, and the IL-level variants
— there is no selection-specific registration method. "Current function"
and "selection" aren't ambient properties of `BinaryView` either; they only
exist as *arguments passed into the command callback*, and which arguments
you get depends entirely on which `register_for_*` method you used:

| Registration | Callback signature | `is_valid` signature |
|---|---|---|
| `register` | `(bv)` | `(bv)` |
| `register_for_address` | `(bv, addr)` | `(bv, addr)` |
| `register_for_range` | `(bv, addr, length)` | `(bv, addr, length)` |
| `register_for_function` | `(bv, func)` | `(bv, func)` |

A command registered via plain `register(bv)` has **no** way to recover an
address, function, or selection — there is nothing to derive it from.
Multi-function "selection" commands need `register_for_range`, where
`(addr, length)` *is* the current UI selection; filter the function list
by address range yourself (`[f for f in bv.functions if addr <= f.start <
addr + length]`). A "current function" for an otherwise whole-binary
command has to come from `register_for_address`'s `addr`, resolved via
`bv.get_functions_containing(addr)[0]`.

Also note `is_valid` must match its registration flavor's signature — an
`is_valid` written as `(bv)` silently gets the wrong number of arguments
if it's plugged into `register_for_function` or `register_for_range`.

**Fix:** `ai/auto-rename/__init__.py` now registers `Auto Rename (Selection)`
via `register_for_range`, and switches the previously plain-`register`
whole-binary commands (`Auto Rename (Filtered)`, `Auto Rename All`,
`Auto Rename All (Choose Strategy)`) to `register_for_address` purely to
get an anchor address, via a `_function_at(bv, addr)` helper. Before adding
a new `PluginCommand.register*` call, check the actual method signature in
`binaryninja/plugin.py` rather than assuming a convenience method exists.

## `TypeError` from `BinaryView.create_tag_type`/`add_tag`

**Symptom:** `TypeError: create_tag_type() takes 2 positional arguments but
3 were given` (or similar for `add_tag`), or tags silently never appear at
the expected address.

**Cause:** The real signatures are `create_tag_type(self, name: str, icon:
str) -> TagType` (no `color` argument — `TagType` has no color concept) and
`add_tag(self, addr: int, tag_type_name: str, data: str, user: bool =
True)`, where `tag_type_name` is the tag type's **name string**, not a
`TagType` object, and `addr` comes first. `core/tags.py` was written
against a guessed `(tag_type, addr, data)` order with a `color` kwarg that
doesn't exist.

**Fix:** `core/tags.py`'s `create_tag_type` drops the `color` parameter,
and `tag_item` calls `bv.add_tag(addr, tag_type_name, data)` directly —
`add_tag` already resolves the tag type by name internally and no-ops if
it isn't registered, so there's no need to look it up yourself first.
