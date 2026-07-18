"""QGraphicsView-based renderer for node-canvas. This is the *only* module
that imports Qt/binaryninjaui -- the domain model (model.py), formats
(formats.py), layout (layout.py) and persistence (persistence.py) stay
Qt-free per docs/adr/0029-node-canvas-architecture.md. CanvasWidget is a
pure observer/renderer: it never owns canvas state, only reflects it.
CanvasPanel wraps it with a canvas-switcher tab bar and a small toolbar.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .core.logging import get_logger
from . import formats, persistence
from .layout import layout_new_nodes
from .model import Canvas, Group, Node

logger = get_logger("node_canvas")

_NODE_WIDTH = 140
_NODE_HEIGHT = 40
_DEFAULT_NODE_COLOR = "#3d5a80"
_DEFAULT_GROUP_COLOR = "#98c1d9"
_ADDRESS_ICON = "ƒ"  # ƒ -- marks a resolved, address-bound node
_UNRESOLVED_ICON = "⚠"  # ⚠ -- marks an address that no longer resolves
_ARROW_SIZE = 9
_NODE_CLIP_MARGIN = 24
_BOX_CLIP_MARGIN = 12

# canvas identity -> open CanvasWidget, so api.export_image() can find a
# live scene to rasterize (image export inherently needs a rendered view).
_open_widgets: dict[int, "CanvasWidget"] = {}


def get_widget_for_canvas(canvas: Canvas):
    return _open_widgets.get(id(canvas))


def _climb_to(item, cls):
    while item is not None and not isinstance(item, cls):
        item = item.parentItem()
    return item


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
        else:
            unresolved = self.node.is_unresolved(bv) if bv is not None else False
            if unresolved:
                label = f"{_UNRESOLVED_ICON} {self.node.address:#x}"
            else:
                resolved = self.node.display_label(bv) if bv is not None else self.node.label
                label = f"{_ADDRESS_ICON} {resolved}"

        fill_color = self.node.color or _DEFAULT_NODE_COLOR
        border_color = self.node.border_color or ("#e63946" if unresolved else "#1d3557")
        self.setBrush(QBrush(QColor(fill_color)))
        self.setPen(QPen(QColor(border_color), 2))
        self._label_item.setText(label)
        self._label_item.setBrush(QBrush(QColor("white")))

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            # Direct mutation, no canvas._notify() -- notifying here would
            # trigger a full scene rebuild mid-drag and yank the item out
            # from under the mouse. Structural changes (add/remove/group)
            # go through the canvas API and do rebuild normally.
            self.node.x = self.pos().x()
            self.node.y = self.pos().y()
            self._canvas_widget.reposition_edges_for(self.node)
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event):
        self._canvas_widget.navigate_to_node(self.node)
        super().mouseDoubleClickEvent(event)


class GroupBoxItem(QGraphicsRectItem):
    """Renders both a collapsed group's representative box (hides its
    members, sits at the default z-order) and an expanded group's
    boundary outline (drawn behind its still-visible members -- see
    CanvasWidget.rebuild_scene, which sets z=-1 for the latter)."""

    def __init__(self, group: Group, canvas_widget: "CanvasWidget", rect: QRectF):
        super().__init__(rect)
        self.group = group
        self._canvas_widget = canvas_widget
        self.setZValue(1)
        color = QColor(group.color or _DEFAULT_GROUP_COLOR)
        color.setAlpha(60 if not group.collapsed else 90)
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor(group.color or _DEFAULT_GROUP_COLOR), 2, Qt.DashLine))
        self.setFlag(QGraphicsItem.ItemIsSelectable)

        label = QGraphicsSimpleTextItem(f"{group.name} ({'+' if group.collapsed else '-'})", self)
        label.setPos(rect.x() + 4, rect.y() + 2)
        font = QFont()
        font.setBold(True)
        label.setFont(font)

    def mouseDoubleClickEvent(self, event):
        canvas = self._canvas_widget.canvas
        if self.group.collapsed:
            canvas.expand_group(self.group)
        else:
            canvas.collapse_group(self.group)
        super().mouseDoubleClickEvent(event)


class EdgeItem(QGraphicsPathItem):
    def __init__(self, src_item, dst_item, color=None, thickness=1.0, count=1, directed=True, edges=None):
        super().__init__()
        self.src_item = src_item
        self.dst_item = dst_item
        self.directed = directed
        self.edges = edges or []  # underlying model Edge(s) this item represents
        self.setZValue(0)
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        pen = QPen(QColor(color or "#6c757d"), max(1.0, float(thickness)))
        if count > 1:
            pen.setStyle(Qt.DashDotLine)
        self.setPen(pen)
        self.update_path()

    def _center(self, item):
        rect = item.rect() if hasattr(item, "rect") else QRectF(0, 0, 0, 0)
        return item.scenePos() + rect.center()

    def _margin_for(self, item):
        return _BOX_CLIP_MARGIN if isinstance(item, GroupBoxItem) else _NODE_CLIP_MARGIN

    def _clip(self, far: QPointF, near: QPointF, margin: float) -> QPointF:
        """A point `margin` back from `near` along the far->near line, so
        edges stop at a node/box's approximate boundary instead of its
        center (and so an arrowhead doesn't render on top of the node)."""
        dx, dy = near.x() - far.x(), near.y() - far.y()
        dist = math.hypot(dx, dy) or 1.0
        return QPointF(near.x() - dx / dist * margin, near.y() - dy / dist * margin)

    def update_path(self):
        p1 = self._center(self.src_item)
        p2 = self._center(self.dst_item)
        p1c = self._clip(p2, p1, self._margin_for(self.src_item))
        p2c = self._clip(p1, p2, self._margin_for(self.dst_item))

        path = QPainterPath(p1c)
        path.lineTo(p2c)
        if self.directed:
            angle = math.atan2(p2c.y() - p1c.y(), p2c.x() - p1c.x())
            for sign in (-1, 1):
                wing_angle = angle + sign * math.radians(28)
                path.moveTo(p2c)
                path.lineTo(p2c - QPointF(math.cos(wing_angle), math.sin(wing_angle)) * _ARROW_SIZE)
        self.setPath(path)


class LegendItem(QGraphicsRectItem):
    def __init__(self, index: int, color: str, label: str, canvas_widget: "CanvasWidget"):
        super().__init__(0, 0, 220, 18)
        self.index = index
        self._canvas_widget = canvas_widget
        self.setPen(QPen(Qt.NoPen))
        self.setBrush(QBrush(Qt.transparent))
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.setZValue(10)

        swatch = QGraphicsRectItem(0, 3, 12, 12, self)
        swatch.setBrush(QBrush(QColor(color)))
        swatch.setPen(QPen(QColor("#222222")))

        text = QGraphicsSimpleTextItem(label, self)
        text.setPos(18, 0)

    def mouseDoubleClickEvent(self, event):
        self._canvas_widget._action_edit_legend_entry(self.index)
        super().mouseDoubleClickEvent(event)


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
        self._legend_items: list[LegendItem] = []
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
        self._legend_items.clear()
        if self.canvas is None:
            return

        visible = self.canvas.visible_graph()

        for group in visible.expanded_boundaries:
            rect = self._group_bounds(group)
            boundary = GroupBoxItem(group, self, rect)
            boundary.setZValue(-1)
            self._scene.addItem(boundary)

        for group in visible.boxes:
            rect = self._group_bounds(group)
            box = GroupBoxItem(group, self, rect)
            self._scene.addItem(box)
            self._node_items[f"group:{group.id}"] = box

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
                color=vedge.color, thickness=vedge.thickness, count=vedge.count, directed=vedge.directed,
                edges=vedge.edges,
            )
            self._scene.addItem(edge_item)
            self._edge_items[id(vedge)] = edge_item

        self._draw_legend()

    def _representative_item(self, element):
        if isinstance(element, Node):
            return self._node_items.get(element.id)
        if isinstance(element, Group):
            return self._node_items.get(f"group:{element.id}")
        return None

    def _group_bounds(self, group: Group) -> QRectF:
        xs, ys = [], []

        def collect(g: Group):
            for node in g.member_nodes:
                xs.extend([node.x, node.x + _NODE_WIDTH])
                ys.extend([node.y, node.y + _NODE_HEIGHT])
            for child in g.child_groups:
                collect(child)

        collect(group)
        if not xs:
            xs, ys = [group.id * 20], [0]
        pad = 20
        return QRectF(min(xs) - pad, min(ys) - pad - 16, max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad + 16)

    def _draw_legend(self):
        if self.canvas is None:
            return
        y = 8
        for index, (color, label) in enumerate(self.canvas.legend):
            item = LegendItem(index, color, label, self)
            item.setPos(8, y)
            self._scene.addItem(item)
            self._legend_items.append(item)
            y += 20

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

        selected_nodes = [i.node for i in self._scene.selectedItems() if isinstance(i, NodeItem)]
        if selected_nodes:
            menu.addAction(f"Remove Selected ({len(selected_nodes)})", lambda: self._action_remove(selected_nodes))
            menu.addAction("Group Selected...", lambda: self._action_group(selected_nodes))
            if len(selected_nodes) == 2:
                menu.addAction("Connect Selected", lambda: self._action_connect_selected(selected_nodes))
            if len(selected_nodes) == 1:
                menu.addAction("Edit Node...", lambda: self._action_edit_node(selected_nodes[0]))
                if selected_nodes[0].address is not None:
                    menu.addAction("Add Callers...", lambda: self._action_add_callers(selected_nodes[0]))
                    menu.addAction("Add Callees...", lambda: self._action_add_callees(selected_nodes[0]))

        group_box = _climb_to(item, GroupBoxItem)
        if group_box is not None:
            action_label = "Expand Group" if group_box.group.collapsed else "Collapse Group"
            menu.addAction(action_label, lambda: self._toggle_group(group_box.group))

        edge_item = _climb_to(item, EdgeItem)
        if edge_item is not None:
            menu.addAction("Edit Edge...", lambda: self._action_edit_edge(edge_item))

        legend_item = _climb_to(item, LegendItem)
        if legend_item is not None:
            menu.addSeparator()
            menu.addAction("Edit Legend Entry...", lambda: self._action_edit_legend_entry(legend_item.index))
            menu.addAction("Delete Legend Entry", lambda: self._action_delete_legend_entry(legend_item.index))
            menu.addAction("Move Legend Entry Up", lambda: self._action_move_legend_entry(legend_item.index, -1))
            menu.addAction("Move Legend Entry Down", lambda: self._action_move_legend_entry(legend_item.index, 1))

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
        label, ok = QInputDialog.getText(self, "Add Node", "Label:")
        if ok and label:
            pos = self.mapToScene(self.viewport().rect().center())
            self.canvas.add_node(label, x=pos.x(), y=pos.y())

    def _action_remove(self, nodes):
        for node in nodes:
            self.canvas.remove_node(node)

    def _action_group(self, nodes):
        name, ok = QInputDialog.getText(self, "Group Selected", "Group name:")
        if ok and name:
            self.canvas.group_nodes(nodes, name)

    def _action_connect_selected(self, nodes):
        if len(nodes) != 2:
            return
        self.canvas.add_edge(nodes[0], nodes[1])
        logger.info("canvas %r: connected node %d -> node %d", self.canvas.name, nodes[0].id, nodes[1].id)

    def _action_edit_node(self, node: Node):
        label, ok = QInputDialog.getText(self, "Edit Node", "Label:", text=node.label)
        if not ok:
            return
        color, ok = QInputDialog.getText(self, "Edit Node", "Fill color (#rrggbb, blank = default):", text=node.color or "")
        if not ok:
            return
        border_color, ok = QInputDialog.getText(self, "Edit Node", "Border color (#rrggbb, blank = default):", text=node.border_color or "")
        if not ok:
            return
        self.canvas.set_node_label(node, label)
        self.canvas.set_node_color(node, color or None)
        self.canvas.set_node_border_color(node, border_color or None)

    def _action_edit_edge(self, edge_item: "EdgeItem"):
        if not edge_item.edges:
            return
        edge = edge_item.edges[0]
        if len(edge_item.edges) > 1:
            # Editing an aggregated (collapsed-group-boundary) edge only
            # touches the first underlying Edge -- expand the group(s) to
            # edit the others individually.
            logger.debug("editing 1 of %d aggregated edges", len(edge_item.edges))
        color, ok = QInputDialog.getText(self, "Edit Edge", "Color (#rrggbb, blank = default):", text=edge.color or "")
        if not ok:
            return
        thickness, ok = QInputDialog.getDouble(self, "Edit Edge", "Thickness:", edge.thickness, 0.5, 20.0, 1)
        if not ok:
            return
        direction, ok = QInputDialog.getItem(
            self, "Edit Edge", "Direction:", ["Directed", "Undirected"], 0 if edge.directed else 1, False,
        )
        if not ok:
            return
        self.canvas.set_edge_color(edge, color or None)
        self.canvas.set_edge_thickness(edge, thickness)
        self.canvas.set_edge_directed(edge, direction == "Directed")

    def _action_add_callers(self, node: Node):
        from . import api

        depth, ok = QInputDialog.getInt(self, "Add Callers", "Depth:", 2, 1, 10)
        if ok:
            api.add_callers(self.bv, self.canvas, node.address, depth=depth)

    def _action_add_callees(self, node: Node):
        from . import api

        depth, ok = QInputDialog.getInt(self, "Add Callees", "Depth:", 2, 1, 10)
        if ok:
            api.add_callees(self.bv, self.canvas, node.address, depth=depth)

    def _action_relayout_prompt(self):
        mode, ok = QInputDialog.getItem(self, "Relayout", "Mode:", ["Auto", "Dot", "Grid"], 0, False)
        if ok:
            self.relayout(mode=mode.lower())

    def _action_export_image(self, scope):
        path, _ = QFileDialog.getSaveFileName(self, "Export Image", "", "PNG (*.png);;PDF (*.pdf)")
        if path:
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
        label, ok = QInputDialog.getText(self, "Add Legend Entry", "Label:")
        if not ok or not label:
            return
        color, ok = QInputDialog.getText(self, "Add Legend Entry", "Color (#rrggbb):", text="#3d5a80")
        if ok and color:
            self.canvas.add_legend_entry(color, label)

    def _action_edit_legend_entry(self, index: int):
        color, label = self.canvas.legend[index]
        new_label, ok = QInputDialog.getText(self, "Edit Legend Entry", "Label:", text=label)
        if not ok or not new_label:
            return
        new_color, ok = QInputDialog.getText(self, "Edit Legend Entry", "Color (#rrggbb):", text=color)
        if not ok or not new_color:
            return
        self.canvas.update_legend_entry(index, color=new_color, label=new_label)

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
            from PySide6.QtGui import QPageSize
            from PySide6.QtPrintSupport import QPrinter

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
            image.save(path)


class CanvasPanel(QWidget):
    """Tab bar of open canvases (plus a trailing '+' tab to create a new
    one) and a small toolbar (relayout + an expand toggle for zoom/layout-
    mode controls), wrapped around a CanvasWidget."""

    def __init__(self, bv, parent=None):
        super().__init__(parent)
        self.bv = bv
        self.canvas_view = CanvasWidget(bv)

        self._suppress_tab_signal = False
        self._plus_index = -1

        self._tab_bar = QTabBar()
        self._tab_bar.setExpanding(False)
        self._tab_bar.setDrawBase(False)
        self._tab_bar.currentChanged.connect(self._on_tab_changed)

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
        if self.canvas_view.canvas is not None and self.canvas_view.canvas.name == name:
            return
        canvas = persistence.load_canvas(self.bv, name)
        if canvas is not None:
            logger.info("switched to canvas %r", name)
            self.canvas_view.set_canvas(canvas)

    def _create_new_canvas(self):
        name, ok = QInputDialog.getText(self, "New Canvas", "Name:")
        if ok and name:
            canvas = Canvas(name)
            persistence.save_canvas(self.bv, canvas)
            logger.info("created canvas %r", name)
            self.canvas_view.set_canvas(canvas)
        self.refresh_tabs()  # also bounces selection off the '+' tab on cancel

    def _on_relayout_clicked(self):
        self.canvas_view.relayout(mode=self._mode_combo.currentText().lower())

    def _on_expand_toggled(self, checked):
        self._expanded_row.setVisible(checked)
