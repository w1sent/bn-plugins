"""Qt rendering for the hex-visualizer sidebar panel: media preview plus a
data-inspector table for whatever's currently selected in a hex/linear
view. This module is Qt-dependent (imports PySide6/binaryninjaui) and is
only imported from __init__.py's GUI-registration path, never from api.py
or the pure-logic modules -- see docs/adr/0037.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHeaderView,
    QLabel,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .core.logging import get_logger
from . import api

logger = get_logger("hex_visualizer")

_PREVIEW_MAX_SIZE = 256  # px, square preview thumbnail


class InspectorPanel(QWidget):
    """Renders one `api.InspectionResult` at a time. Owns no selection
    state itself -- the sidebar widget in __init__.py decides *when* to
    call `set_selection`, this only decides *how* to draw the result."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self.clear()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.header_label = QLabel("No selection")
        self.header_label.setWordWrap(True)
        layout.addWidget(self.header_label)

        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.preview_label)

        self.format_label = QLabel()
        self.format_label.setWordWrap(True)
        layout.addWidget(self.format_label)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Type", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        # Read-only cells still need explicit copy support -- QTableWidget
        # doesn't wire Ctrl+C or a context menu to clipboard by default.
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_table_context_menu)
        QShortcut(QKeySequence.Copy, self.table, self._copy_selection)
        layout.addWidget(self.table, stretch=1)

    def clear(self):
        self.header_label.setText("No selection")
        self.preview_label.clear()
        self.preview_label.setVisible(False)
        self.format_label.clear()
        self.format_label.setVisible(False)
        self.table.setRowCount(0)

    def set_selection(self, bv, start: int, end: int):
        if bv is None or end <= start:
            self.clear()
            return

        try:
            result = api.inspect(bv, start, end - start)
        except Exception:
            logger.exception("hex-visualizer: inspect failed for %#x-%#x", start, end)
            self.clear()
            self.header_label.setText(f"{start:#x} - {end:#x}: read failed")
            return

        length = result.end - result.start
        truncated = " (truncated preview)" if result.truncated else ""
        plural = "" if length == 1 else "s"
        self.header_label.setText(f"{result.start:#x} - {result.end:#x} ({length} byte{plural}){truncated}")

        self._update_preview(result)
        self._update_table(result)

    def _update_preview(self, result):
        match = result.format_match
        if match is None:
            self.preview_label.setVisible(False)
            self.format_label.setVisible(False)
            return

        detail_text = ", ".join(f"{k}: {v}" for k, v in match.details.items())
        label_text = match.label + (f" -- {detail_text}" if detail_text else "")
        if result.carved_length:
            note = " (carve truncated)" if result.carve_truncated else ""
            label_text += f" [carved: {result.carved_length} bytes{note}]"
        self.format_label.setText(label_text)
        self.format_label.setVisible(True)

        if not match.previewable:
            self.preview_label.setVisible(False)
            return

        image = QImage.fromData(result.data)
        if image.isNull():
            self.preview_label.setVisible(False)
            return
        pixmap = QPixmap.fromImage(image).scaled(
            _PREVIEW_MAX_SIZE, _PREVIEW_MAX_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.preview_label.setPixmap(pixmap)
        self.preview_label.setVisible(True)

    def _update_table(self, result):
        rows = result.rows
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(row.label))
            self.table.setItem(i, 1, QTableWidgetItem(row.value))

    def _copy_selection(self):
        items = self.table.selectedItems()
        if not items:
            return
        rows: dict = {}
        for item in items:
            rows.setdefault(item.row(), {})[item.column()] = item.text()
        lines = [
            "\t".join(cols.get(c, "") for c in sorted(cols))
            for _row, cols in sorted(rows.items())
        ]
        QApplication.clipboard().setText("\n".join(lines))

    def _show_table_context_menu(self, pos):
        menu = QMenu(self.table)
        copy_action = menu.addAction("Copy")
        copy_action.setEnabled(bool(self.table.selectedItems()))
        copy_action.triggered.connect(self._copy_selection)
        menu.exec(self.table.viewport().mapToGlobal(pos))
