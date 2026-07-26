"""QGraphicsView-based renderer for node-canvas. This is the *only* module
that imports Qt/binaryninjaui -- the domain model (model.py), formats
(formats.py), layout (layout.py) and persistence (persistence.py) stay
Qt-free per docs/adr/0029-node-canvas-architecture.md. CanvasWidget is a
pure observer/renderer: it never owns canvas state, only reflects it.
CanvasPanel wraps it with a canvas-switcher tab bar and a small toolbar.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QSpinBox,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .core.logging import get_logger
from . import formats, persistence
from .layout import (
    NODE_HEIGHT as _NODE_HEIGHT,
    NODE_WIDTH as _NODE_WIDTH,
    estimate_node_width,
    layout_new_nodes,
)
from .model import DEFAULT_EDGE_STYLE, EDGE_STYLES, Canvas, Group, Node

logger = get_logger("node_canvas")

_DEFAULT_NODE_COLOR = "#3d5a80"
_DEFAULT_GROUP_COLOR = "#98c1d9"
_NODE_ICONS = {
    "function": "ƒ",  # ƒ -- resolved to a BN Function
    "data": "◆",  # ◆ -- resolved to a BN data variable
    "symbol": "●",  # ● -- resolved to some other symbol (import, export, ...)
}
_UNRESOLVED_ICON = "⚠"  # ⚠ -- marks an address that no longer resolves
_ARROW_SIZE = 9
_NODE_LABEL_MARGIN = 24.0  # left/right inset a NodeItem reserves around its label text
_GROUP_PADDING = 20
_GROUP_LABEL_HEIGHT = 16
_EDGE_STYLE_LABELS = {"solid": "Solid", "dashed": "Dashed", "dotted": "Dotted", "dashdot": "Dash-Dot"}
_EDGE_QT_PEN_STYLES = {"solid": Qt.SolidLine, "dashed": Qt.DashLine, "dotted": Qt.DotLine, "dashdot": Qt.DashDotLine}

# canvas identity -> open CanvasWidget, so api.export_image() can find a
# live scene to rasterize (image export inherently needs a rendered view).
_open_widgets: dict[int, "CanvasWidget"] = {}


def get_widget_for_canvas(canvas: Canvas):
    return _open_widgets.get(id(canvas))


def _climb_to(item, cls):
    while item is not None and not isinstance(item, cls):
        item = item.parentItem()
    return item


def _text_color_for_background(bg: QColor) -> str:
    luminance = 0.299 * bg.red() + 0.587 * bg.green() + 0.114 * bg.blue()
    return "#000000" if luminance > 140 else "#ffffff"


_MEMORY_PREVIEW_MAX = 48


def try_decode_string(data: bytes):
    """None if `data` doesn't look like a printable string -- shared by
    __init__.py's "Add Memory Location" PluginCommand (BN view context
    menu) and this module's own sidebar action, so both formats agree."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if text and all(32 <= ord(c) < 127 or c in "\t\n\r" for c in text):
        return text
    return None


# -- form dialog (replaces chains of QInputDialogs) ----------------------


def _field(key, label, kind="text", default="", choices=None, range=None, decimals=1):
    return {
        "key": key, "label": label, "kind": kind, "default": default,
        "choices": choices, "range": range, "decimals": decimals,
    }


class FormDialog(QDialog):
    """A single-form dialog for multi-field add/edit actions -- one OK/
    Cancel round trip instead of a chain of QInputDialogs.

    `on_change`, if given, is called as `on_change(dialog)` whenever any
    non-preview field's value changes (including once up front, to seed
    the initial preview) -- it should call `dialog.set_preview(key, text)`
    for whichever "preview" fields it wants to update. Used by e.g. Add
    Memory Location's live hex/string preview."""

    def __init__(self, parent, title: str, fields: list[dict], on_change=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._widgets = {}
        self._on_change = on_change

        form = QFormLayout()
        for spec in fields:
            kind = spec["kind"]
            default = spec["default"]
            row_widget = None
            if kind == "choice":
                w = QComboBox()
                w.addItems(spec["choices"] or [])
                if default in (spec["choices"] or []):
                    w.setCurrentText(default)
            elif kind == "int":
                w = QSpinBox()
                lo, hi = spec["range"] or (0, 1000000)
                w.setRange(lo, hi)
                w.setValue(int(default) if default != "" else lo)
            elif kind == "float":
                w = QDoubleSpinBox()
                lo, hi = spec["range"] or (0.0, 1000.0)
                w.setRange(lo, hi)
                w.setDecimals(spec["decimals"])
                w.setValue(float(default) if default != "" else lo)
            elif kind == "checkbox":
                w = QCheckBox()
                w.setChecked(bool(default))
            elif kind == "color":
                w = QLineEdit(str(default or ""))
                row_widget = self._make_color_row(w)
            elif kind == "preview":
                w = QLineEdit(str(default or ""))
                w.setReadOnly(True)
            else:  # "text"
                w = QLineEdit(str(default or ""))
            self._widgets[spec["key"]] = w
            form.addRow(spec["label"], row_widget if row_widget is not None else w)
            if kind != "preview" and on_change is not None:
                self._watch(w)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        if on_change is not None:
            on_change(self)  # seed the initial preview

    def _make_color_row(self, line: QLineEdit) -> QWidget:
        button = QToolButton()
        button.setText("🎨")
        button.setToolTip("Pick color...")

        def pick():
            initial = QColor(line.text())
            if not initial.isValid():
                initial = QColor(_DEFAULT_NODE_COLOR)
            color = QColorDialog.getColor(initial, self, "Pick Color")
            if color.isValid():
                line.setText(color.name())

        button.clicked.connect(pick)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(line, 1)
        row_layout.addWidget(button)
        return row

    def _watch(self, w):
        if isinstance(w, QComboBox):
            w.currentTextChanged.connect(lambda _: self._on_change(self))
        elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
            w.valueChanged.connect(lambda _: self._on_change(self))
        elif isinstance(w, QCheckBox):
            w.toggled.connect(lambda _: self._on_change(self))
        elif isinstance(w, QLineEdit):
            w.textChanged.connect(lambda _: self._on_change(self))

    def set_preview(self, key: str, text: str):
        w = self._widgets.get(key)
        if isinstance(w, QLineEdit):
            w.setText(text)

    def values(self) -> dict:
        result = {}
        for key, w in self._widgets.items():
            if isinstance(w, QComboBox):
                result[key] = w.currentText()
            elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                result[key] = w.value()
            elif isinstance(w, QCheckBox):
                result[key] = w.isChecked()
            else:
                result[key] = w.text()
        return result

    @staticmethod
    def get(parent, title: str, fields: list[dict], on_change=None):
        dlg = FormDialog(parent, title, fields, on_change=on_change)
        if dlg.exec() == QDialog.Accepted:
            return dlg.values()
        return None


class NodeItem(QGraphicsRectItem):
    def __init__(self, node: Node, canvas_widget: "CanvasWidget"):
        super().__init__(0, 0, _NODE_WIDTH, _NODE_HEIGHT)
        self.node = node
        self._canvas_widget = canvas_widget
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setZValue(2)
        self.setPos(node.x, node.y)
        self._label_item = QGraphicsSimpleTextItem(self)
        self._label_item.setPos(6, 10)
        self.refresh()

    def refresh(self):
        bv = self._canvas_widget.bv
        unresolved = False
        if self.node.address is None:
            label = self.node.label
        elif bv is None:
            label = self.node.label
        else:
            kind = self.node.resolve_kind(bv)
            if kind is None:
                unresolved = True
                label = f"{_UNRESOLVED_ICON} {self.node.address:#x}"
            else:
                icon = _NODE_ICONS.get(kind, "")
                label = f"{icon} {self.node.display_label(bv)}"

        fill_color = self.node.color or _DEFAULT_NODE_COLOR
        border_color = self.node.border_color or ("#e63946" if unresolved else "#1d3557")
        self.setBrush(QBrush(QColor(fill_color)))
        self.setPen(QPen(QColor(border_color), 2))
        self._label_item.setText(label)
        self._label_item.setBrush(QBrush(QColor("white")))

        # Resize to fit the actual rendered label (never smaller than the
        # canonical box) instead of clipping/overlapping neighbors -- see
        # layout.py's estimate_node_width for the headless-safe approximation
        # of this used to space nodes *before* real font metrics exist.
        width = max(_NODE_WIDTH, QFontMetrics(self._label_item.font()).horizontalAdvance(label) + _NODE_LABEL_MARGIN)
        if width != self.rect().width():
            self.setRect(0, 0, width, _NODE_HEIGHT)
            self._canvas_widget.reposition_edges_for(self.node)
            if self.node.group is not None:
                self._canvas_widget.resize_boundary_for(self.node.group)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            # Direct mutation, no canvas._notify() -- notifying here would
            # trigger a full scene rebuild mid-drag and yank the item out
            # from under the mouse. Structural changes (add/remove/group)
            # go through the canvas API and do rebuild normally.
            self.node.x = self.pos().x()
            self.node.y = self.pos().y()
            self._canvas_widget.reposition_edges_for(self.node)
            if self.node.group is not None and not self._canvas_widget._suspend_resize:
                self._canvas_widget.resize_boundary_for(self.node.group)
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event):
        super().mouseDoubleClickEvent(event)
        self._canvas_widget.navigate_to_node(self.node)


class GroupBoxItem(QGraphicsRectItem):
    """Renders both a collapsed group's representative box (hides its
    members) and an expanded group's boundary outline (drawn behind its
    still-visible members -- see CanvasWidget.rebuild_scene, which sets
    z=-1 for the latter).

    Movable: dragging the box translates every (possibly nested) member
    node by the same delta (see CanvasWidget.translate_group). Dragging a
    member node the other way auto-grows/shrinks the box to keep fitting
    it -- see CanvasWidget.resize_boundary_for -- so a node is never
    visually "outside" its group's box; the box just always equals the
    padded bounding rect of its members.
    """

    def __init__(self, group: Group, canvas_widget: "CanvasWidget", x: float, y: float, width: float, height: float):
        super().__init__(0, 0, width, height)
        self.group = group
        self._canvas_widget = canvas_widget
        self._user_dragging = False
        self.setPos(x, y)
        self._last_pos = QPointF(x, y)
        self.setZValue(1)
        self.setFlags(
            QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self._apply_style()

        self._label_item = QGraphicsSimpleTextItem(self)
        self._label_item.setPos(4, 2)
        font = QFont()
        font.setBold(True)
        self._label_item.setFont(font)
        self.refresh_label()

    def _apply_style(self):
        color = QColor(self.group.color or _DEFAULT_GROUP_COLOR)
        color.setAlpha(90 if self.group.collapsed else 60)
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor(self.group.color or _DEFAULT_GROUP_COLOR), 2, Qt.DashLine))

    def refresh_label(self):
        self._label_item.setText(f"{self.group.name} ({'+' if self.group.collapsed else '-'})")

    def set_geometry(self, x: float, y: float, width: float, height: float):
        self.setRect(0, 0, width, height)
        self.setPos(x, y)

    def mousePressEvent(self, event):
        self._user_dragging = True
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._user_dragging = False
        super().mouseReleaseEvent(event)
        self._canvas_widget._save()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            delta = value - self._last_pos
            self._last_pos = value
            if self._user_dragging and (delta.x() or delta.y()):
                self._canvas_widget.translate_group(self.group, delta.x(), delta.y())
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event):
        # super() first: collapse/expand triggers a full scene rebuild
        # that destroys this item, so nothing may touch `self` afterward.
        super().mouseDoubleClickEvent(event)
        canvas = self._canvas_widget.canvas
        if self.group.collapsed:
            canvas.expand_group(self.group)
        else:
            canvas.collapse_group(self.group)


class EdgeItem(QGraphicsPathItem):
    def __init__(self, src_item, dst_item, color=None, thickness=None, count=1, arrow_start=False, arrow_end=True, style=DEFAULT_EDGE_STYLE, edges=None):
        super().__init__()
        self.src_item = src_item
        self.dst_item = dst_item
        self.arrow_start = arrow_start
        self.arrow_end = arrow_end
        self.count = count
        self.edges = edges or []  # underlying model Edge(s) this item represents
        self.setZValue(0)
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        pen = QPen(QColor(color or "#6c757d"), max(1.0, float(thickness if thickness is not None else 3.0)))
        # The line style always matches the model's edge.style exactly --
        # it must never be silently overridden (e.g. to cue "aggregated
        # edge"), or the Edit Edge form would show a style that doesn't
        # match what's actually drawn. Aggregation is instead shown via a
        # "xN" count label, added below.
        pen.setStyle(_EDGE_QT_PEN_STYLES.get(style, Qt.SolidLine))
        self.setPen(pen)
        self._count_label = None
        if count > 1:
            self._count_label = QGraphicsSimpleTextItem(f"×{count}", self)
            self._count_label.setBrush(QBrush(QColor(color or "#6c757d")))
        self.update_path()

    def _center(self, item):
        rect = item.rect() if hasattr(item, "rect") else QRectF(0, 0, 0, 0)
        return item.scenePos() + rect.center()

    def _clip_to_rect(self, other: QPointF, rect: QRectF) -> QPointF:
        """The exact point where the segment from `other` to `rect`'s
        center crosses `rect`'s boundary -- edges always terminate right
        at a node's or group box's edge, never its center, regardless of
        how big the box is (a collapsed group's box can be far larger
        than a plain node)."""
        center = rect.center()
        dx, dy = center.x() - other.x(), center.y() - other.y()
        if dx == 0 and dy == 0:
            return center
        half_w, half_h = rect.width() / 2, rect.height() / 2
        tx = half_w / abs(dx) if dx != 0 else float("inf")
        ty = half_h / abs(dy) if dy != 0 else float("inf")
        t = min(tx, ty, 1.0)
        return QPointF(center.x() - dx * t, center.y() - dy * t)

    def _endpoint(self, item, other_center: QPointF) -> QPointF:
        rect = item.sceneBoundingRect() if hasattr(item, "sceneBoundingRect") else QRectF(other_center, other_center)
        return self._clip_to_rect(other_center, rect)

    def update_path(self):
        c1 = self._center(self.src_item)
        c2 = self._center(self.dst_item)
        p1c = self._endpoint(self.src_item, c2)
        p2c = self._endpoint(self.dst_item, c1)

        path = QPainterPath(p1c)
        path.lineTo(p2c)
        angle = math.atan2(p2c.y() - p1c.y(), p2c.x() - p1c.x())
        if self.arrow_end:
            for sign in (-1, 1):
                wing_angle = angle + sign * math.radians(28)
                path.moveTo(p2c)
                path.lineTo(p2c - QPointF(math.cos(wing_angle), math.sin(wing_angle)) * _ARROW_SIZE)
        if self.arrow_start:
            back_angle = angle + math.pi
            for sign in (-1, 1):
                wing_angle = back_angle + sign * math.radians(28)
                path.moveTo(p1c)
                path.lineTo(p1c - QPointF(math.cos(wing_angle), math.sin(wing_angle)) * _ARROW_SIZE)
        self.setPath(path)
        if self._count_label is not None:
            mid = QPointF((p1c.x() + p2c.x()) / 2, (p1c.y() + p2c.y()) / 2)
            box = self._count_label.boundingRect()
            self._count_label.setPos(mid.x() - box.width() / 2, mid.y() - box.height() / 2)


class LegendContainerItem(QGraphicsRectItem):
    """The whole legend as one draggable item -- individual entries are
    non-interactive child items purely for rendering; this container does
    its own hit-testing (by y-offset) for double-click/context-menu."""

    ENTRY_HEIGHT = 20

    def __init__(self, canvas_widget: "CanvasWidget", entries: list[tuple[str, str]], x: float, y: float):
        width = 220
        height = max(1, len(entries)) * self.ENTRY_HEIGHT + 8
        super().__init__(0, 0, width, height)
        self._canvas_widget = canvas_widget
        self._entry_count = len(entries)
        self.setPos(x, y)
        self.setZValue(10)
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
            | QGraphicsItem.ItemIgnoresTransformations
        )

        bg = canvas_widget.palette().color(canvas_widget.backgroundRole())
        text_color = _text_color_for_background(bg)
        panel = QColor(bg)
        panel.setAlpha(160)
        self.setBrush(QBrush(panel))
        self.setPen(QPen(QColor("#888888")))

        for i, (color, label) in enumerate(entries):
            y_off = 4 + i * self.ENTRY_HEIGHT
            swatch = QGraphicsRectItem(4, y_off + 3, 12, 12, self)
            swatch.setBrush(QBrush(QColor(color)))
            swatch.setPen(QPen(QColor("#222222")))
            swatch.setAcceptedMouseButtons(Qt.NoButton)

            text = QGraphicsSimpleTextItem(label, self)
            text.setPos(22, y_off)
            text.setBrush(QBrush(QColor(text_color)))
            text.setAcceptedMouseButtons(Qt.NoButton)

    def index_at(self, local_pos: QPointF):
        index = int((local_pos.y() - 4) // self.ENTRY_HEIGHT)
        if 0 <= index < self._entry_count:
            return index
        return None

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            # Direct mutation, no notify -- same reasoning as NodeItem:
            # avoid a mid-drag scene rebuild. Persisted on mouse release.
            self._canvas_widget.canvas.legend_x = value.x()
            self._canvas_widget.canvas.legend_y = value.y()
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self._canvas_widget._save()

    def mouseDoubleClickEvent(self, event):
        super().mouseDoubleClickEvent(event)
        index = self.index_at(event.pos())
        if index is not None:
            self._canvas_widget._action_edit_legend_entry(index)


class CanvasWidget(QGraphicsView):
    """The canvas surface itself. Kept as a plain QGraphicsView subclass so
    it's independently testable/reusable outside CanvasPanel."""

    def __init__(self, bv, canvas: Canvas | None = None, parent=None):
        self._scene = QGraphicsScene()
        super().__init__(self._scene, parent)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)

        self.bv = bv
        self.canvas: Canvas | None = None
        self._node_items: dict[int, NodeItem] = {}
        self._edge_items: dict[int, EdgeItem] = {}
        self._group_items: dict[int, GroupBoxItem] = {}
        self._legend_container: LegendContainerItem | None = None
        self._suspend_resize = False
        self._panning = False
        self._pan_start = QPointF()

        if canvas is not None:
            self.set_canvas(canvas)

    # -- canvas binding ---------------------------------------------------

    def set_canvas(self, canvas: Canvas):
        if self.canvas is not None:
            self.canvas.remove_observer(self._on_canvas_event)
            _open_widgets.pop(id(self.canvas), None)
        self.canvas = canvas
        canvas.add_observer(self._on_canvas_event)
        _open_widgets[id(canvas)] = self
        self.rebuild_scene()

    def closeEvent(self, event):
        if self.canvas is not None:
            self.canvas.remove_observer(self._on_canvas_event)
            _open_widgets.pop(id(self.canvas), None)
        super().closeEvent(event)

    def _on_canvas_event(self, event):
        self.rebuild_scene()
        self._save()

    def _save(self):
        if self.bv is not None and self.canvas is not None:
            persistence.save_canvas(self.bv, self.canvas)

    # -- rendering ----------------------------------------------------

    def rebuild_scene(self):
        self._scene.clear()
        self._node_items.clear()
        self._edge_items.clear()
        self._group_items.clear()
        self._legend_container = None
        if self.canvas is None:
            return

        visible = self.canvas.visible_graph()

        for group in visible.expanded_boundaries:
            x, y, w, h = self._group_bounds(group)
            boundary = GroupBoxItem(group, self, x, y, w, h)
            boundary.setZValue(-1)
            self._scene.addItem(boundary)
            self._group_items[group.id] = boundary

        for group in visible.boxes:
            x, y, w, h = self._group_bounds(group)
            box = GroupBoxItem(group, self, x, y, w, h)
            self._scene.addItem(box)
            self._group_items[group.id] = box

        for node in visible.nodes:
            item = NodeItem(node, self)
            self._scene.addItem(item)
            self._node_items[node.id] = item

        for vedge in visible.edges:
            src_item = self._representative_item(vedge.src)
            dst_item = self._representative_item(vedge.dst)
            if src_item is None or dst_item is None:
                continue
            edge_item = EdgeItem(
                src_item, dst_item,
                color=vedge.color, thickness=vedge.thickness, count=vedge.count,
                arrow_start=vedge.arrow_start, arrow_end=vedge.arrow_end,
                style=vedge.style, edges=vedge.edges,
            )
            self._scene.addItem(edge_item)
            self._edge_items[id(vedge)] = edge_item

        self._draw_legend()

    def _representative_item(self, element):
        if isinstance(element, Node):
            return self._node_items.get(element.id)
        if isinstance(element, Group):
            return self._group_items.get(element.id)
        return None

    def _node_render_width(self, node: Node) -> float:
        """Actual rendered width if `node`'s item already exists in this
        scene build, else the headless estimate layout.py uses -- keeps
        group boundaries correctly sized whether or not their members have
        been constructed yet (rebuild_scene creates group boxes before
        nodes)."""
        item = self._node_items.get(node.id)
        if item is not None:
            return item.rect().width()
        return estimate_node_width(node.label)

    def _group_bounds(self, group: Group) -> tuple[float, float, float, float]:
        xs, ys = [], []

        def collect(g: Group):
            for node in g.member_nodes:
                xs.extend([node.x, node.x + self._node_render_width(node)])
                ys.extend([node.y, node.y + _NODE_HEIGHT])
            for child in g.child_groups:
                collect(child)

        collect(group)
        if not xs:
            xs, ys = [0.0, 0.0], [0.0, 0.0]
        x = min(xs) - _GROUP_PADDING
        y = min(ys) - _GROUP_PADDING - _GROUP_LABEL_HEIGHT
        w = (max(xs) - min(xs)) + 2 * _GROUP_PADDING
        h = (max(ys) - min(ys)) + 2 * _GROUP_PADDING + _GROUP_LABEL_HEIGHT
        return x, y, w, h

    def resize_boundary_for(self, group: Group):
        """Re-fit `group`'s box (and every ancestor's) to its members'
        current bounding rect. Safe to call while a NodeItem drag is live:
        GroupBoxItem only cascades a *move* to its members when it itself
        is the one being dragged (see GroupBoxItem._user_dragging)."""
        while group is not None:
            box = self._group_items.get(group.id)
            if box is not None:
                x, y, w, h = self._group_bounds(group)
                box.set_geometry(x, y, w, h)
            group = group.parent

    def translate_group(self, group: Group, dx: float, dy: float):
        """Rigidly move every (possibly nested) member node of `group`,
        and every nested child group's box, by the same delta -- called
        when the user drags the group's box. A rigid shift never changes
        any box's size, so resize_boundary_for is suppressed for the
        whole subtree being moved (it would otherwise recompute bounds
        from a half-updated set of node positions mid-loop and cascade
        back into another translate_group call via the moved boxes'
        own itemChange). Ancestors *outside* `group` do need a resize
        once the shift is complete, since their bounding box genuinely
        changes -- that happens after, unsuppressed."""

        def all_nodes(g: Group):
            result = list(g.member_nodes)
            for child in g.child_groups:
                result.extend(all_nodes(child))
            return result

        def all_child_groups(g: Group):
            result = []
            for child in g.child_groups:
                result.append(child)
                result.extend(all_child_groups(child))
            return result

        self._suspend_resize = True
        try:
            for node in all_nodes(group):
                node.x += dx
                node.y += dy
                item = self._node_items.get(node.id)
                if item is not None:
                    item.setPos(node.x, node.y)
            for child in all_child_groups(group):
                box = self._group_items.get(child.id)
                if box is not None:
                    box.setPos(box.pos().x() + dx, box.pos().y() + dy)
        finally:
            self._suspend_resize = False

        if group.parent is not None:
            self.resize_boundary_for(group.parent)

    def _draw_legend(self):
        if self.canvas is None or not self.canvas.legend:
            return
        container = LegendContainerItem(self, self.canvas.legend, self.canvas.legend_x, self.canvas.legend_y)
        self._scene.addItem(container)
        self._legend_container = container

    def reposition_edges_for(self, node: Node):
        node_item = self._node_items.get(node.id)
        if node_item is None:
            return
        for edge_item in self._edge_items.values():
            if edge_item.src_item is node_item or edge_item.dst_item is node_item:
                edge_item.update_path()

    # -- navigation / toast ---------------------------------------------

    def navigate_to_node(self, node: Node):
        if node.address is None:
            return
        if self.bv is not None and node.is_unresolved(self.bv):
            self._show_toast(f"Address {node.address:#x} no longer resolves to a valid BN entity")
            return
        import binaryninjaui as ui

        ctx = ui.UIContext.activeContext()
        if ctx is not None and self.bv is not None:
            ctx.navigateForBinaryView(self.bv, node.address)

    def _show_toast(self, message: str):
        import binaryninjaui as ui

        ctx = ui.UIContext.activeContext()
        mw = ctx.mainWindow() if ctx is not None else None
        if mw is not None:
            mw.statusBar().showMessage(message, 4000)

    # -- zoom -------------------------------------------------------------

    def zoom(self, factor: float):
        self.scale(factor, factor)

    def reset_zoom(self):
        self.resetTransform()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.zoom(factor)
            event.accept()
            return
        super().wheelEvent(event)

    # -- layout -------------------------------------------------------

    def relayout(self, mode: str = "auto"):
        if self.canvas is None:
            return
        selected = [i.node for i in self._scene.selectedItems() if isinstance(i, NodeItem)]
        targets = selected if selected else list(self.canvas.nodes.values())
        if not targets:
            return
        logger.info("canvas %r: relayout (mode=%s) of %d node(s)%s", self.canvas.name, mode, len(targets), " (selection)" if selected else " (all)")
        layout_new_nodes(self.canvas, targets, mode=mode)

    # -- panning (middle-drag) --------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._panning = False
            self.unsetCursor()
            return
        super().mouseReleaseEvent(event)
        self._save()  # persist any position change from a just-finished drag

    # -- context menu ---------------------------------------------------

    def contextMenuEvent(self, event):
        if self.canvas is None:
            return
        item = self.itemAt(event.pos())
        menu = QMenu(self)

        menu.addAction("Add Node...", self._action_add_node)
        menu.addAction("Add Memory Location...", self._action_add_memory_location)

        selected_nodes = [i.node for i in self._scene.selectedItems() if isinstance(i, NodeItem)]
        if selected_nodes:
            menu.addAction(f"Remove Selected ({len(selected_nodes)})", lambda: self._action_remove(selected_nodes))
            menu.addAction("Group Selected...", lambda: self._action_group(selected_nodes))
            if self.canvas.groups:
                menu.addAction("Add Selected to Group...", lambda: self._action_add_to_group(selected_nodes))
            if any(n.group is not None for n in selected_nodes):
                menu.addAction("Remove Selected from Group", lambda: self._action_remove_from_group(selected_nodes))
            if len(selected_nodes) == 2:
                menu.addAction("Connect Selected", lambda: self._action_connect_selected(selected_nodes))
            menu.addAction("Copy Content", lambda: self._action_copy_content(selected_nodes))
            if len(selected_nodes) == 1:
                menu.addAction("Edit Node...", lambda: self._action_edit_node(selected_nodes[0]))
                if selected_nodes[0].address is not None:
                    menu.addAction("Add Callers...", lambda: self._action_add_callers(selected_nodes[0]))
                    menu.addAction("Add Callees...", lambda: self._action_add_callees(selected_nodes[0]))

        group_box = _climb_to(item, GroupBoxItem)
        if group_box is not None:
            action_label = "Expand Group" if group_box.group.collapsed else "Collapse Group"
            menu.addAction(action_label, lambda: self._toggle_group(group_box.group))
            menu.addAction("Edit Group...", lambda: self._action_edit_group(group_box.group))
            menu.addAction("Remove Group (keep nodes)", lambda: self._action_remove_group(group_box.group))

        edge_item = _climb_to(item, EdgeItem)
        if edge_item is not None:
            menu.addAction("Edit Edge...", lambda: self._action_edit_edge(edge_item))

        legend_container = _climb_to(item, LegendContainerItem)
        if legend_container is not None:
            local_pos = legend_container.mapFromScene(self.mapToScene(event.pos()))
            index = legend_container.index_at(local_pos)
            if index is not None:
                menu.addSeparator()
                menu.addAction("Edit Legend Entry...", lambda: self._action_edit_legend_entry(index))
                menu.addAction("Delete Legend Entry", lambda: self._action_delete_legend_entry(index))
                menu.addAction("Move Legend Entry Up", lambda: self._action_move_legend_entry(index, -1))
                menu.addAction("Move Legend Entry Down", lambda: self._action_move_legend_entry(index, 1))

        menu.addSeparator()
        menu.addAction("Relayout (selection or all)...", self._action_relayout_prompt)

        menu.addSeparator()
        export_menu = menu.addMenu("Export")
        export_menu.addAction("Image (current view)...", lambda: self._action_export_image("current"))
        export_menu.addAction("Image (full canvas)...", lambda: self._action_export_image("full"))
        export_menu.addAction("Mermaid...", self._action_export_mermaid)
        export_menu.addAction("DOT...", self._action_export_dot)
        export_menu.addAction("JSON...", self._action_export_json)

        import_menu = menu.addMenu("Import")
        import_menu.addAction("DOT...", self._action_import_dot)
        import_menu.addAction("JSON...", self._action_import_json)

        menu.addAction("Add Legend Entry...", self._action_add_legend_entry)

        menu.exec(event.globalPos())

    def _toggle_group(self, group: Group):
        if group.collapsed:
            self.canvas.expand_group(group)
        else:
            self.canvas.collapse_group(group)

    def _action_add_node(self):
        values = FormDialog.get(self, "Add Node", [_field("label", "Label")])
        if values and values["label"]:
            pos = self.mapToScene(self.viewport().rect().center())
            self.canvas.add_node(values["label"], x=pos.x(), y=pos.y())

    def _parse_addr(self, text: str) -> Optional[int]:
        try:
            return int(text, 16) if text.lower().startswith("0x") else int(text, 0)
        except ValueError:
            return None

    def _memory_preview_text(self, addr: Optional[int], length: int, representation: str) -> str:
        if addr is None:
            return "(invalid address)"
        if representation == "Address only" or self.bv is None or length <= 0:
            return ""
        try:
            data = self.bv.read(addr, min(length, _MEMORY_PREVIEW_MAX))
        except Exception:
            return "(read failed)"
        truncated = "..." if length > _MEMORY_PREVIEW_MAX else ""
        if representation == "String":
            text = try_decode_string(data)
            return f"{text}{truncated}" if text is not None else "(not printable)"
        return f"{data.hex()}{truncated}"

    def _action_add_memory_location(self):
        default_addr, default_len = "", 1
        try:
            import binaryninjaui as ui

            ctx = ui.UIContext.activeContext()
            vf = ctx.getCurrentViewFrame() if ctx else None
            if vf is not None:
                start, end = vf.getSelectionOffsets()
                default_addr = f"{start:#x}"
                default_len = max(1, end - start)
        except Exception:
            pass

        def update_preview(dlg: FormDialog):
            v = dlg.values()
            addr = self._parse_addr(v["address"])
            dlg.set_preview("preview", self._memory_preview_text(addr, int(v["length"]), v["representation"]))

        values = FormDialog.get(self, "Add Memory Location", [
            _field("address", "Address (hex)", default=default_addr),
            _field("length", "Length (bytes)", "int", default_len, range=(1, 65536)),
            _field("representation", "Representation", "choice", "Hex", choices=["Hex", "String", "Address only"]),
            _field("preview", "Preview", "preview"),
        ], on_change=update_preview)
        if not values or not values["address"]:
            return

        addr = self._parse_addr(values["address"])
        if addr is None:
            QMessageBox.warning(self, "Add Memory Location", f"Not a valid address: {values['address']!r}")
            return

        length = int(values["length"])
        representation = values["representation"]
        label = f"{addr:#x}"
        if representation != "Address only" and length > 0:
            body = self._memory_preview_text(addr, length, representation)
            label = f"{addr:#x}: {body} [{addr:#x}-{addr + length:#x}]"
        self.canvas.add_node(label, address=addr)

    def _action_remove(self, nodes):
        for node in nodes:
            self.canvas.remove_node(node)

    def _action_group(self, nodes):
        values = FormDialog.get(self, "Group Selected", [
            _field("name", "Group name"),
            _field("color", "Color", "color", default=_DEFAULT_GROUP_COLOR),
        ])
        if values and values["name"]:
            self.canvas.group_nodes(nodes, values["name"], color=values["color"] or None)

    def _action_add_to_group(self, nodes):
        names = [g.name for g in self.canvas.groups.values()]
        values = FormDialog.get(self, "Add to Group", [_field("group", "Group", "choice", names[0], choices=names)])
        if not values:
            return
        group = next((g for g in self.canvas.groups.values() if g.name == values["group"]), None)
        if group is not None:
            self.canvas.add_nodes_to_group(nodes, group)

    def _action_remove_from_group(self, nodes):
        self.canvas.remove_nodes_from_group(nodes)

    def _action_remove_group(self, group):
        self.canvas.remove_group(group, keep_members=True)

    def _action_edit_group(self, group: Group):
        values = FormDialog.get(self, "Edit Group", [
            _field("name", "Name", default=group.name),
            _field("color", "Color", "color", default=group.color or _DEFAULT_GROUP_COLOR),
        ])
        if not values or not values["name"]:
            return
        self.canvas.set_group_name(group, values["name"])
        self.canvas.set_group_color(group, values["color"] or None)

    def _action_connect_selected(self, nodes):
        if len(nodes) != 2:
            return
        self.canvas.add_edge(nodes[0], nodes[1])
        logger.info("canvas %r: connected node %d -> node %d", self.canvas.name, nodes[0].id, nodes[1].id)

    def _action_copy_content(self, nodes):
        text = "\n".join(node.display_label(self.bv) if self.bv is not None else node.label for node in nodes)
        QApplication.clipboard().setText(text)
        logger.info("canvas %r: copied content of %d node(s) to clipboard", self.canvas.name, len(nodes))

    def _action_edit_node(self, node: Node):
        values = FormDialog.get(self, "Edit Node", [
            _field("label", "Label", default=node.label),
            _field("color", "Fill color (blank = default)", "color", default=node.color or ""),
            _field("border_color", "Border color (blank = default)", "color", default=node.border_color or ""),
        ])
        if not values:
            return
        self.canvas.set_node_label(node, values["label"])
        self.canvas.set_node_color(node, values["color"] or None)
        self.canvas.set_node_border_color(node, values["border_color"] or None)

    def _action_edit_edge(self, edge_item: "EdgeItem"):
        if not edge_item.edges:
            return
        edge = edge_item.edges[0]
        if len(edge_item.edges) > 1:
            # Editing an aggregated (collapsed-group-boundary) edge only
            # touches the first underlying Edge -- expand the group(s) to
            # edit the others individually.
            logger.debug("editing 1 of %d aggregated edges", len(edge_item.edges))
        style_choices = [_EDGE_STYLE_LABELS[s] for s in EDGE_STYLES]
        values = FormDialog.get(self, "Edit Edge", [
            _field("color", "Color (blank = default)", "color", default=edge.color or ""),
            _field("thickness", "Thickness", "float", edge.thickness, range=(0.5, 20.0)),
            _field("style", "Style", "choice", _EDGE_STYLE_LABELS[edge.style], choices=style_choices),
            _field("arrow_start", "Arrow at start (src)", "checkbox", edge.arrow_start),
            _field("arrow_end", "Arrow at end (dst)", "checkbox", edge.arrow_end),
            _field("reverse", "Swap direction (src <-> dst)", "checkbox", False),
        ])
        if not values:
            return
        self.canvas.set_edge_color(edge, values["color"] or None)
        self.canvas.set_edge_thickness(edge, values["thickness"])
        style_by_label = {v: k for k, v in _EDGE_STYLE_LABELS.items()}
        self.canvas.set_edge_style(edge, style_by_label.get(values["style"], DEFAULT_EDGE_STYLE))
        self.canvas.set_edge_arrows(edge, arrow_start=values["arrow_start"], arrow_end=values["arrow_end"])
        if values["reverse"]:
            self.canvas.reverse_edge(edge)

    def _action_add_callers(self, node: Node):
        from . import api

        values = FormDialog.get(self, "Add Callers", [_field("depth", "Depth", "int", 2, range=(1, 10))])
        if values:
            api.add_callers(self.bv, self.canvas, node.address, depth=values["depth"])

    def _action_add_callees(self, node: Node):
        from . import api

        values = FormDialog.get(self, "Add Callees", [_field("depth", "Depth", "int", 2, range=(1, 10))])
        if values:
            api.add_callees(self.bv, self.canvas, node.address, depth=values["depth"])

    def _action_relayout_prompt(self):
        values = FormDialog.get(self, "Relayout", [_field("mode", "Mode", "choice", "Auto", choices=["Auto", "Dot", "Grid"])])
        if values:
            self.relayout(mode=values["mode"].lower())

    def _action_export_image(self, scope):
        path, selected_filter = QFileDialog.getSaveFileName(self, "Export Image", "", "PNG (*.png);;PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith((".png", ".pdf")):
            # Some native/GTK save dialogs don't append an extension even
            # with a filter selected -- QImage.save() infers format from
            # the extension and just silently no-ops (returns False, no
            # exception) if it can't, so the file never gets written.
            path += ".pdf" if "pdf" in selected_filter.lower() else ".png"
        self.export_image(path, scope=scope)

    def _action_export_mermaid(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Mermaid", "", "Markdown (*.md)")
        if path:
            formats.export_mermaid(self.canvas, path)

    def _action_export_dot(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export DOT", "", "DOT (*.dot)")
        if path:
            formats.export_dot(self.canvas, path)

    def _action_export_json(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export JSON", "", "JSON (*.json)")
        if path:
            formats.export_json(self.canvas, path)

    def _action_import_dot(self):
        from . import api

        path, _ = QFileDialog.getOpenFileName(self, "Import DOT", "", "DOT (*.dot)")
        if path:
            api.import_dot(self.canvas, path)

    def _action_import_json(self):
        from . import api

        path, _ = QFileDialog.getOpenFileName(self, "Import JSON", "", "JSON (*.json)")
        if path:
            api.import_json(self.canvas, path)

    def _action_add_legend_entry(self):
        values = FormDialog.get(self, "Add Legend Entry", [
            _field("label", "Label"),
            _field("color", "Color", "color", default=_DEFAULT_NODE_COLOR),
        ])
        if values and values["label"] and values["color"]:
            self.canvas.add_legend_entry(values["color"], values["label"])

    def _action_edit_legend_entry(self, index: int):
        color, label = self.canvas.legend[index]
        values = FormDialog.get(self, "Edit Legend Entry", [
            _field("label", "Label", default=label),
            _field("color", "Color", "color", default=color),
        ])
        if values and values["label"] and values["color"]:
            self.canvas.update_legend_entry(index, color=values["color"], label=values["label"])

    def _action_delete_legend_entry(self, index: int):
        self.canvas.remove_legend_entry(index)

    def _action_move_legend_entry(self, index: int, delta: int):
        self.canvas.move_legend_entry(index, index + delta)

    # -- image export (Qt-dependent, lives here per ADR-0029) -----------

    def export_image(self, path: str, scope: str = "current"):
        if scope == "current":
            rect = self.mapToScene(self.viewport().rect()).boundingRect()
        else:
            rect = self._scene.itemsBoundingRect()

        if rect.isEmpty():
            rect = QRectF(0, 0, 1, 1)

        if path.lower().endswith(".pdf"):
            try:
                from PySide6.QtGui import QPageSize
                from PySide6.QtPrintSupport import QPrinter
            except ImportError as exc:
                # QtPrintSupport isn't always usable -- e.g. a system
                # PySide6 install with a Qt runtime version mismatched
                # against BN's bundled Qt -- and without this it fails
                # with an unhandled exception, so from the user's
                # perspective the export just silently never happens.
                logger.error("PDF export unavailable (QtPrintSupport failed to import: %s)", exc)
                self._show_toast("PDF export unavailable in this environment -- try PNG instead")
                return

            printer = QPrinter(QPrinter.HighResolution)
            printer.setOutputFormat(QPrinter.PdfFormat)
            printer.setOutputFileName(path)
            printer.setPageSize(QPageSize(rect.size(), QPageSize.Point))
            painter = QPainter(printer)
            self._scene.render(painter, source=rect)
            painter.end()
        else:
            image = QImage(max(1, int(rect.width())), max(1, int(rect.height())), QImage.Format_ARGB32)
            image.fill(Qt.transparent)
            painter = QPainter(image)
            self._scene.render(painter, source=rect)
            painter.end()
            if not image.save(path, "PNG"):
                logger.error("failed to write image export to %r", path)
                self._show_toast(f"Image export failed: could not write {path}")


class _ClosableTabBar(QTabBar):
    """QTabBar has no built-in "middle-click to close" signal."""

    middleClicked = Signal(int)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            index = self.tabAt(event.pos())
            if index >= 0:
                self.middleClicked.emit(index)
                event.accept()
                return
        super().mouseReleaseEvent(event)


class CanvasPanel(QWidget):
    """Tab bar of open canvases (plus a trailing '+' tab to create a new
    one, and middle-click to delete) and a small toolbar (relayout + an
    expand toggle for zoom/layout-mode controls), wrapped around a
    CanvasWidget."""

    def __init__(self, bv, parent=None):
        super().__init__(parent)
        self.bv = bv
        self.canvas_view = CanvasWidget(bv)

        self._suppress_tab_signal = False
        self._plus_index = -1

        self._tab_bar = _ClosableTabBar()
        self._tab_bar.setExpanding(False)
        self._tab_bar.setDrawBase(False)
        self._tab_bar.currentChanged.connect(self._on_tab_changed)
        self._tab_bar.middleClicked.connect(self._on_tab_middle_clicked)

        self._relayout_btn = QToolButton()
        self._relayout_btn.setText("⟳")  # ⟳
        self._relayout_btn.setToolTip("Relayout the selection (or the whole canvas if nothing is selected), using the mode below")
        self._relayout_btn.clicked.connect(self._on_relayout_clicked)

        self._expand_btn = QToolButton()
        self._expand_btn.setText("▾")  # ▾
        self._expand_btn.setCheckable(True)
        self._expand_btn.setToolTip("More canvas tools (zoom, layout mode)")
        self._expand_btn.toggled.connect(self._on_expand_toggled)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.addWidget(self._tab_bar, 1)
        top_row.addWidget(self._relayout_btn)
        top_row.addWidget(self._expand_btn)

        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["Auto", "Dot", "Grid"])
        self._mode_combo.setToolTip("Layout engine used by the relayout button (⟳)")

        zoom_out_btn = QToolButton()
        zoom_out_btn.setText("−")  # −
        zoom_out_btn.clicked.connect(lambda: self.canvas_view.zoom(1 / 1.2))
        zoom_reset_btn = QToolButton()
        zoom_reset_btn.setText("100%")
        zoom_reset_btn.clicked.connect(self.canvas_view.reset_zoom)
        zoom_in_btn = QToolButton()
        zoom_in_btn.setText("+")
        zoom_in_btn.clicked.connect(lambda: self.canvas_view.zoom(1.2))

        self._expanded_row = QWidget()
        expanded_layout = QHBoxLayout(self._expanded_row)
        expanded_layout.setContentsMargins(4, 2, 4, 2)
        expanded_layout.addWidget(QLabel("Layout:"))
        expanded_layout.addWidget(self._mode_combo)
        expanded_layout.addSpacing(12)
        expanded_layout.addWidget(QLabel("Zoom:"))
        expanded_layout.addWidget(zoom_out_btn)
        expanded_layout.addWidget(zoom_reset_btn)
        expanded_layout.addWidget(zoom_in_btn)
        expanded_layout.addStretch(1)
        self._expanded_row.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(top_row)
        layout.addWidget(self._expanded_row)
        layout.addWidget(self.canvas_view, 1)

        self.refresh_tabs()

    # -- bv / canvas binding ---------------------------------------------

    def bind_bv(self, bv):
        self.bv = bv
        self.canvas_view.bv = bv

    def set_canvas(self, canvas: Canvas):
        self.canvas_view.set_canvas(canvas)
        if self.bv is not None:
            persistence.set_active_canvas_name(self.bv, canvas.name)
        self.refresh_tabs()

    def refresh_tabs(self):
        self._suppress_tab_signal = True
        while self._tab_bar.count():
            self._tab_bar.removeTab(0)
        names = persistence.list_canvas_names(self.bv) if self.bv is not None else []
        current_name = self.canvas_view.canvas.name if self.canvas_view.canvas else None
        for name in names:
            self._tab_bar.addTab(name)
        self._plus_index = self._tab_bar.addTab("+")
        if current_name in names:
            self._tab_bar.setCurrentIndex(names.index(current_name))
        self._suppress_tab_signal = False

    def _on_tab_changed(self, index):
        if self._suppress_tab_signal or index < 0 or self.bv is None:
            return
        if index == self._plus_index:
            self._create_new_canvas()
            return
        name = self._tab_bar.tabText(index)
        persistence.set_active_canvas_name(self.bv, name)
        if self.canvas_view.canvas is not None and self.canvas_view.canvas.name == name:
            return
        canvas = persistence.load_canvas(self.bv, name)
        if canvas is not None:
            logger.info("switched to canvas %r", name)
            self.canvas_view.set_canvas(canvas)

    def _on_tab_middle_clicked(self, index):
        if index == self._plus_index or index < 0 or self.bv is None:
            return
        name = self._tab_bar.tabText(index)
        answer = QMessageBox.question(
            self, "Delete Canvas", f"Delete canvas {name!r}? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        persistence.delete_canvas(self.bv, name)
        logger.info("deleted canvas %r (middle-click)", name)

        if self.canvas_view.canvas is not None and self.canvas_view.canvas.name == name:
            remaining = persistence.list_canvas_names(self.bv)
            if remaining:
                next_canvas = persistence.load_canvas(self.bv, remaining[0])
            else:
                next_canvas = Canvas(persistence.generate_canvas_name(self.bv))
                persistence.save_canvas(self.bv, next_canvas)
            self.set_canvas(next_canvas)
        else:
            self.refresh_tabs()

    def _create_new_canvas(self):
        values = FormDialog.get(self, "New Canvas", [_field("name", "Name")])
        if values and values["name"]:
            canvas = Canvas(values["name"])
            persistence.save_canvas(self.bv, canvas)
            logger.info("created canvas %r", canvas.name)
            self.set_canvas(canvas)
        else:
            self.refresh_tabs()  # bounces selection off the '+' tab on cancel

    def _on_relayout_clicked(self):
        self.canvas_view.relayout(mode=self._mode_combo.currentText().lower())

    def _on_expand_toggled(self, checked):
        self._expanded_row.setVisible(checked)
