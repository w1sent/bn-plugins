"""Shared "framework detected" status bar indicator for framework plugins
(dotnet-native-aot, flutter, ...) -- mirrors Binary Ninja's own native
platform/architecture status bar label: a small permanent widget that
reflects whichever binary view is currently focused, updating live as the
user switches tabs/views.

There is no plugin extension point for Binary Ninja's Triage view (its
header/summary section is closed C++ UI -- confirmed by inspecting
`binaryninjaui` at runtime: no `Triage`-named class or method exists beyond
its entry in `ViewType.getTypes()`), so this is status-bar-only.

Usage (call once, at plugin import time -- cheap/idempotent, safe to call
from a headless import since everything GUI-related is deferred):

    from .core.framework_status import register_framework_indicator
    register_framework_indicator("dotnet_native_aot", ".NET NativeAOT", "🧩", _has_rtr_module)

`detect(bv) -> bool` should be reasonably cheap on repeat calls; its result
is cached per (key, bv) in `bv.session_data`, so each registered detector
runs at most once per binary view.

Like `ai/mcp-server/gui.py`'s status bar indicator, all binaryninjaui/Qt
access is marshalled onto BN's main thread via `execute_on_main_thread_and_wait`
-- calling Qt directly off the main thread can crash BN.
"""

import binaryninja

_detectors = {}  # key -> (label, icon, detect_fn)
_widget = None
_notification = None


def _cache_key(key):
    return f"_framework_status.{key}"


def _cached_detect(bv, key, detect_fn):
    cache_key = _cache_key(key)
    cached = bv.session_data.get(cache_key)
    if cached is not None:
        return cached

    try:
        found = bool(detect_fn(bv))
    except Exception:
        found = False

    bv.session_data[cache_key] = found
    return found


def _status_bar_widget(mw):
    """Return the shared status bar QLabel, creating it on first use.
    Recreates it if the previous one was torn down with its window (e.g.
    BN's main window was recreated), which raises RuntimeError on access."""
    global _widget
    if _widget is not None:
        try:
            _widget.isVisible()
            return _widget
        except RuntimeError:
            _widget = None

    from PySide6.QtWidgets import QLabel

    _widget = QLabel()
    _widget.setVisible(False)
    mw.statusBar().addPermanentWidget(_widget)
    return _widget


def _update_for_bv(bv):
    if not binaryninja.core_ui_enabled():
        return

    def do_update():
        import binaryninjaui as ui

        contexts = ui.UIContext.allContexts()
        if not contexts:
            return
        mw = contexts[0].mainWindow()
        if mw is None:
            return
        widget = _status_bar_widget(mw)

        if bv is None:
            widget.setVisible(False)
            return

        matches = [
            (label, icon)
            for key, (label, icon, detect_fn) in _detectors.items()
            if _cached_detect(bv, key, detect_fn)
        ]

        if not matches:
            widget.setVisible(False)
            return

        widget.setText("  ".join(f"{icon} {label}" for label, icon in matches))
        widget.setToolTip("Detected framework(s): " + ", ".join(label for label, _ in matches))
        widget.setVisible(True)

    binaryninja.execute_on_main_thread_and_wait(do_update)


def _extract_bv(args):
    """UIContextNotification callback signatures vary by hook (some pass a
    ViewFrame, some pass the BinaryView directly as `data`); pull whichever
    is present out of the raw args rather than hardcoding positions."""
    for arg in args:
        get_bv = getattr(arg, "getCurrentBinaryView", None)
        if get_bv is not None:
            try:
                bv = get_bv()
            except Exception:
                bv = None
            if bv is not None:
                return bv
    for arg in args:
        if hasattr(arg, "session_data") and hasattr(arg, "segments"):
            return arg
    return None


def _make_notification():
    import binaryninjaui as ui

    class _FrameworkStatusNotification(ui.UIContextNotification):
        def OnViewChange(self, *args, **kwargs):
            _update_for_bv(_extract_bv(args))

        def OnAddressChange(self, *args, **kwargs):
            _update_for_bv(_extract_bv(args))

        def OnAfterOpenFile(self, *args, **kwargs):
            _update_for_bv(_extract_bv(args))

        def OnAfterCloseFile(self, *args, **kwargs):
            _update_for_bv(None)

    return _FrameworkStatusNotification()


def register_framework_indicator(key, label, icon, detect_fn):
    """Register a framework detector to contribute to the shared status bar
    indicator. Safe to call more than once (e.g. plugin reload) -- the same
    key just overwrites its previous registration. No-op headless."""
    if not binaryninja.core_ui_enabled():
        return

    _detectors[key] = (label, icon, detect_fn)

    global _notification

    def do_register():
        import binaryninjaui as ui

        global _notification
        if _notification is None:
            _notification = _make_notification()
            ui.UIContext.registerNotification(_notification)

        contexts = ui.UIContext.allContexts()
        if not contexts:
            return
        vf = contexts[0].getCurrentViewFrame()
        bv = vf.getCurrentBinaryView() if vf else None
        _update_for_bv(bv)

    binaryninja.execute_on_main_thread_and_wait(do_register)
