import sys
from pathlib import Path

_plugin_dir = Path(__file__).parent.resolve()
_deps = _plugin_dir / ".deps"
if _deps.is_dir() and str(_deps) not in sys.path:
    sys.path.insert(0, str(_deps))

import binaryninja
from binaryninja import PluginCommand

from .core.logging import get_logger
from . import api, persistence

logger = get_logger("node_canvas")

# One CanvasWidget per bv that currently has the sidebar panel open --
# populated by CanvasSidebarWidget.__init__/closeEvent below. PluginCommand
# actions mutate through this live widget's Canvas instance (never a
# separately-loaded copy) so there's exactly one in-memory Canvas per bv,
# matching widget.py's own observer-driven autosave.
#
# Keyed by bv.file.filename, not id(bv): BN can hand back a fresh Python
# proxy object wrapping the same underlying BinaryView on different calls
# (e.g. a PluginCommand callback's `bv` vs. the sidebar's `self.bv`), so
# `id(bv)` is not a stable key across calls even for "the same" binary.
_widgets_by_bv: dict[str, "CanvasSidebarWidget"] = {}


def _bv_key(bv) -> str:
    return bv.file.filename


def _load_or_create_active_canvas(bv):
    name = persistence.get_active_canvas_name(bv)
    canvas = persistence.load_canvas(bv, name) if name else None
    if canvas is None:
        canvas = api.create_canvas(bv, persistence.generate_canvas_name(bv))
        persistence.set_active_canvas_name(bv, canvas.name)
        logger.info("bv %r: no active canvas, created %r", bv.file.filename, canvas.name)
    return canvas


def _get_open_canvas_widget(bv):
    """The live widget backing this bv's sidebar panel, if the panel has
    been opened at least once (see CanvasSidebarWidget registration
    below). Returns None if the panel has never been opened -- BN's
    sidebar widgets are created lazily on first click of the icon."""
    return _widgets_by_bv.get(_bv_key(bv))


def _require_open_widget(bv):
    widget = _get_open_canvas_widget(bv)
    if widget is None:
        logger.info(
            "Node Canvas: open the Node Canvas sidebar panel first (click its icon in "
            "the sidebar), then retry -- this inserts into whichever canvas is "
            "currently shown there."
        )
        return None
    return widget.canvas_widget


def _run_on_main_thread(fn):
    binaryninja.execute_on_main_thread_and_wait(fn)


def _add_function_to_canvas(bv, addr):
    def do():
        canvas_widget = _require_open_widget(bv)
        if canvas_widget is None:
            return
        func = bv.get_function_at(addr)
        label = func.name if func else f"{addr:#x}"
        api.add_node(canvas_widget.canvas, label, address=addr)
        logger.info("canvas %r: added function %r via PluginCommand", canvas_widget.canvas.name, label)

    _run_on_main_thread(do)


def _add_callers_to_canvas(bv, addr):
    def do():
        canvas_widget = _require_open_widget(bv)
        if canvas_widget is None:
            return
        api.add_callers(bv, canvas_widget.canvas, addr, depth=2)

    _run_on_main_thread(do)


def _add_callees_to_canvas(bv, addr):
    def do():
        canvas_widget = _require_open_widget(bv)
        if canvas_widget is None:
            return
        api.add_callees(bv, canvas_widget.canvas, addr, depth=2)

    _run_on_main_thread(do)


_MEMORY_PREVIEW_MAX = 48


def _add_memory_location_to_canvas(bv, addr, length):
    def do():
        from .widget import try_decode_string  # Qt-dependent; deferred like _register_sidebar's imports

        canvas_widget = _require_open_widget(bv)
        if canvas_widget is None:
            return

        label = f"{addr:#x}"
        if length > 1:
            data = bv.read(addr, min(length, _MEMORY_PREVIEW_MAX))
            truncated = "..." if length > _MEMORY_PREVIEW_MAX else ""
            as_string = try_decode_string(data)
            end = addr + length
            if as_string is not None:
                label = f'{addr:#x}: "{as_string}{truncated}" [{addr:#x}-{end:#x}]'
            else:
                label = f"{addr:#x}: {data.hex()}{truncated} [{addr:#x}-{end:#x}]"

        api.add_node(canvas_widget.canvas, label, address=addr)
        logger.info("canvas %r: added memory location %r via PluginCommand", canvas_widget.canvas.name, label)

    _run_on_main_thread(do)


PluginCommand.register_for_range(
    "Node Canvas\\Add Memory Location",
    "Insert the selected address (or address range) into the active Node Canvas, including a "
    "hex or decoded-string preview of its bytes when more than one byte is selected.",
    _add_memory_location_to_canvas,
)

PluginCommand.register_for_address(
    "Node Canvas\\Add Function",
    "Insert the function at this address into the active Node Canvas (the canvas currently "
    "shown in the Node Canvas sidebar panel).",
    _add_function_to_canvas,
)
PluginCommand.register_for_address(
    "Node Canvas\\Add Callers",
    "Insert this function and its callers (depth 2) into the active Node Canvas.",
    _add_callers_to_canvas,
)
PluginCommand.register_for_address(
    "Node Canvas\\Add Callees",
    "Insert this function and its callees (depth 2) into the active Node Canvas.",
    _add_callees_to_canvas,
)


def _register_sidebar():
    """GUI-only registration, deferred and guarded per CONTEXT.md's
    binaryninjaui-main-thread-only rule -- construct Qt/binaryninjaui
    objects on BN's main thread, and only if a UI is actually present
    (this module must stay importable headless, e.g. under execute_script)."""
    if not binaryninja.core_ui_enabled():
        return

    def do_register():
        from PySide6.QtGui import QColor, QImage, QPainter
        from PySide6.QtWidgets import QVBoxLayout
        import binaryninjaui as ui

        from .widget import CanvasPanel

        class CanvasSidebarWidget(ui.SidebarWidget):
            def __init__(self, name, frame, data):
                ui.SidebarWidget.__init__(self, name)
                self.bv = data
                self.panel = CanvasPanel(self.bv)
                self.canvas_widget = self.panel.canvas_view  # the live CanvasWidget; used by PluginCommand actions
                layout = QVBoxLayout()
                layout.setContentsMargins(0, 0, 0, 0)
                layout.addWidget(self.panel)
                self.setLayout(layout)

                if self.bv is not None:
                    canvas = _load_or_create_active_canvas(self.bv)
                    self.panel.set_canvas(canvas)
                    _widgets_by_bv[_bv_key(self.bv)] = self
                    logger.debug("sidebar panel opened for %r, canvas %r", self.bv.file.filename, canvas.name)

            def notifyViewChanged(self, view_frame):
                bv = view_frame.getCurrentBinaryView() if view_frame else None
                if bv is None:
                    return
                # Compare by filename, not Python identity: BN can hand back
                # a fresh Python proxy object wrapping the same underlying
                # BinaryView on repeated calls, so `bv is self.bv` false-
                # positives on "changed" for every notifyViewChanged tick --
                # including ones fired by purely-internal sidebar clicks
                # (e.g. switching canvas tabs) -- which was clobbering the
                # user's tab switch by reloading the persisted active
                # canvas right back over it.
                if self.bv is not None and _bv_key(bv) == _bv_key(self.bv):
                    self.bv = bv
                    self.panel.bind_bv(bv)
                    return
                if self.bv is not None:
                    _widgets_by_bv.pop(_bv_key(self.bv), None)
                self.bv = bv
                self.panel.bind_bv(bv)
                canvas = _load_or_create_active_canvas(bv)
                self.panel.set_canvas(canvas)
                _widgets_by_bv[_bv_key(bv)] = self
                logger.debug("sidebar panel switched to %r, canvas %r", bv.file.filename, canvas.name)

        class CanvasSidebarWidgetType(ui.SidebarWidgetType):
            def __init__(self):
                icon = QImage(56, 56, QImage.Format_ARGB32)
                icon.fill(QColor(0, 0, 0, 0))
                painter = QPainter(icon)
                painter.setBrush(QColor(255, 255, 255))
                painter.setPen(QColor(255, 255, 255))
                painter.drawEllipse(8, 8, 16, 16)
                painter.drawEllipse(32, 8, 16, 16)
                painter.drawEllipse(20, 32, 16, 16)
                painter.setPen(QColor(255, 255, 255))
                painter.drawLine(16, 16, 28, 40)
                painter.drawLine(40, 16, 28, 40)
                painter.end()
                super().__init__(icon, "Node Canvas")

            def createWidget(self, frame, data):
                return CanvasSidebarWidget("Node Canvas", frame, data)

            def defaultLocation(self):
                return ui.SidebarWidgetLocation.RightReference

            def contextSensitivity(self):
                return ui.SidebarContextSensitivity.SelfManagedSidebarContext

        widget_type = CanvasSidebarWidgetType()
        ui.Sidebar.addSidebarWidgetType(widget_type)
        logger.debug("registered Node Canvas sidebar widget type")

    _run_on_main_thread(do_register)


_register_sidebar()

logger.info("node-canvas loaded")
