import sys
from pathlib import Path

_plugin_dir = Path(__file__).parent.resolve()
_deps = _plugin_dir / ".deps"
if _deps.is_dir() and str(_deps) not in sys.path:
    sys.path.insert(0, str(_deps))

import binaryninja

from .core.logging import get_logger

logger = get_logger("hex_visualizer")


def _run_on_main_thread(fn):
    binaryninja.execute_on_main_thread_and_wait(fn)


def _register_sidebar():
    """GUI-only registration, deferred and guarded per CONTEXT.md's
    binaryninjaui-main-thread-only rule -- construct Qt/binaryninjaui
    objects on BN's main thread, and only if a UI is actually present
    (this module must stay importable headless, e.g. under execute_script,
    same as node-canvas)."""
    if not binaryninja.core_ui_enabled():
        return

    def do_register():
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QImage, QPainter, QPen
        from PySide6.QtWidgets import QVBoxLayout
        import binaryninjaui as ui

        from .widget import InspectorPanel

        class HexVisualizerSidebarWidget(ui.SidebarWidget):
            def __init__(self, name, frame, data):
                ui.SidebarWidget.__init__(self, name)
                self.frame = frame
                self.panel = InspectorPanel()
                layout = QVBoxLayout()
                layout.setContentsMargins(0, 0, 0, 0)
                layout.addWidget(self.panel)
                self.setLayout(layout)
                self._refresh()

            def _refresh(self):
                if self.frame is None:
                    self.panel.clear()
                    return
                try:
                    bv = self.frame.getCurrentBinaryView()
                    start, end = self.frame.getSelectionOffsets()
                except Exception:
                    logger.exception("hex-visualizer: failed to read current selection")
                    self.panel.clear()
                    return
                self.panel.set_selection(bv, start, end)

            def notifyViewChanged(self, view_frame):
                self.frame = view_frame
                self._refresh()

            def notifyOffsetChanged(self, offset):
                self._refresh()

        class HexVisualizerSidebarWidgetType(ui.SidebarWidgetType):
            def __init__(self):
                icon = QImage(56, 56, QImage.Format_ARGB32)
                icon.fill(QColor(0, 0, 0, 0))
                painter = QPainter(icon)
                pen = QPen(QColor(255, 255, 255))
                pen.setWidth(4)
                pen.setCapStyle(Qt.RoundCap)
                painter.setPen(pen)
                painter.setRenderHint(QPainter.Antialiasing)
                # Simple magnifying-glass-over-grid glyph.
                for x in (14, 26, 38):
                    painter.drawLine(x, 10, x, 34)
                for y in (10, 22, 34):
                    painter.drawLine(14, y, 38, y)
                painter.drawEllipse(28, 28, 16, 16)
                painter.drawLine(40, 40, 48, 48)
                painter.end()
                super().__init__(icon, "Hex Visualizer")

            def createWidget(self, frame, data):
                return HexVisualizerSidebarWidget("Hex Visualizer", frame, data)

            def defaultLocation(self):
                return ui.SidebarWidgetLocation.RightReference

            def contextSensitivity(self):
                return ui.SidebarContextSensitivity.PerPaneSidebarContext

        widget_type = HexVisualizerSidebarWidgetType()
        ui.Sidebar.addSidebarWidgetType(widget_type)
        logger.debug("registered Hex Visualizer sidebar widget type")

    _run_on_main_thread(do_register)


_register_sidebar()

logger.info("hex-visualizer loaded")
