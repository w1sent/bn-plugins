# Framework plugins must show a 🧩 status bar indicator

Every plugin in `frameworks/` (dotnet-native-aot, flutter, go, react-native,
swift, unity-il2cpp, wasm, compiled-python, ...) exists to recover
metadata for one specific runtime/framework, and every one of them needs
some way to tell the user "this binary looks like a match" without the
user having to already know that or run a command speculatively. Rather
than each plugin inventing its own notice (message box, log line, custom
panel), they share one mechanism.

**Every framework plugin must register a detector with
`core/framework_status.register_framework_indicator(key, label, icon,
detect_fn)`**, using the fixed icon `🧩` and the framework's display name
(e.g. `register_framework_indicator("dotnet_native_aot", ".NET NativeAOT",
"🧩", _has_rtr_module)`). This produces a small permanent status bar label
that lights up next to Binary Ninja's own native platform/architecture
indicator whenever `detect_fn(bv)` matches the currently focused binary
view, and updates live as the user switches tabs. `detect_fn` should be a
real, cheap-ish structural check (a known symbol, section, or magic
signature) -- the same check the plugin's `PluginCommand._is_valid` uses to
decide whether to show its own manual command, not a heuristic invented
just for the indicator. Detection results are cached per-`bv` by the
shared module, so a slower fallback scan still only runs once per binary.

This was prototyped for dotnet-native-aot (see its `_has_rtr_module`) and
must be added to every other framework plugin as part of implementing it,
not bolted on afterwards -- a framework plugin without a status bar
detector is incomplete per this ADR.

**Explicitly out of scope**: Binary Ninja's Triage view has no plugin
extension point (confirmed by inspecting `binaryninjaui` at runtime -- no
class or method exists for injecting rows into its header/summary section,
only its `ViewType` registration is visible). Do not attempt to hack
around this (e.g. by holding a reference to Triage's internal Qt widgets
and mutating them directly) -- the status bar indicator is the whole
mechanism per this ADR, consistent with ADR-0024's preference for BN's
existing native surfaces over custom UI.
