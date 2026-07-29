"""The Agentic Triage view: a Qt widget registered as a BN `ViewType`, so it
appears in the same view-selector dropdown as Linear/Graph/Triage (unlike
`ux/node-canvas`, which is a sidebar dock widget -- this is a full view tab,
per the "Where does the editing UI live" decision in
docs/adr/0035-shared-evidence-store-and-context-prompt.md).

Top pane shows the AI/deterministic output (read-only); bottom pane shows
the user's edit -- the context prompt other AI tools actually read (see
core/context.py). Buttons trigger the quick (single-call) or full (agent)
enhancement passes, both of which run on a background thread (ADR-0006)
with results marshalled back to the main thread before touching any Qt
widget or the BN metadata store.

NOTE: this file has not been exercised in a live Binary Ninja GUI session
-- it could not be, in the environment this was written in (headless;
`import binaryninjaui` raises outside a running BN GUI process). Treat the
ViewType/View plumbing as unverified until it's been opened in a real BN
window.
"""

from __future__ import annotations

from .core.context import (
    build_baseline,
    clear_user_edit,
    get_enhancer_output,
    get_user_edit,
    is_stale,
    set_user_edit,
)
from .core.logging import get_logger
from . import api

logger = get_logger("agentic_triage")

_VIEW_NAME = "Agentic Triage"
_VIEW_LONG_NAME = "Agentic Triage"


def register_view_type():
    """GUI-only registration, deferred and guarded exactly like
    ux/node-canvas's `_register_sidebar` -- must stay importable headless
    (e.g. under execute_script), and binaryninjaui/Qt objects must only be
    constructed on BN's main thread."""
    import binaryninja

    if not binaryninja.core_ui_enabled():
        return

    def do_register():
        import binaryninjaui as ui

        widget_type = _AgenticTriageViewType()
        ui.ViewType.registerViewType(widget_type)
        logger.debug("registered Agentic Triage view type")

    binaryninja.execute_on_main_thread_and_wait(do_register)


def _build_view_class():
    """Built lazily inside register_view_type() (via _AgenticTriageViewType
    below) so PySide6/binaryninjaui are only imported once a GUI is
    actually present."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QHBoxLayout,
        QLabel,
        QPlainTextEdit,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )
    from binaryninja import execute_on_main_thread
    import binaryninjaui as ui

    class AgenticTriageView(QWidget, ui.View):
        def __init__(self, parent, data):
            QWidget.__init__(self, parent)
            ui.View.__init__(self)
            self.setupView(self)
            self.bv = data

            self.staleness_label = QLabel()
            self.staleness_label.setStyleSheet("color: #c9a227;")

            self.top_pane = QPlainTextEdit()
            self.top_pane.setReadOnly(True)

            self.bottom_pane = QPlainTextEdit()

            quick_btn = QPushButton("Quick Enhance")
            quick_btn.clicked.connect(self._on_quick_enhance)
            full_btn = QPushButton("Run Full Analysis")
            full_btn.clicked.connect(self._on_full_analysis)
            copy_btn = QPushButton("Copy to User Input ↓")
            copy_btn.clicked.connect(self._on_copy_to_user_input)
            refresh_btn = QPushButton("Refresh")
            refresh_btn.clicked.connect(self._refresh)
            self._action_buttons = [quick_btn, full_btn, copy_btn, refresh_btn]

            top_buttons = QHBoxLayout()
            top_buttons.addWidget(quick_btn)
            top_buttons.addWidget(full_btn)
            top_buttons.addWidget(copy_btn)
            top_buttons.addWidget(refresh_btn)
            top_buttons.addStretch(1)

            save_btn = QPushButton("Save Edit")
            save_btn.clicked.connect(self._on_save_edit)
            revert_btn = QPushButton("Revert to AI Output")
            revert_btn.clicked.connect(self._on_revert_edit)

            bottom_buttons = QHBoxLayout()
            bottom_buttons.addWidget(save_btn)
            bottom_buttons.addWidget(revert_btn)
            bottom_buttons.addStretch(1)

            layout = QVBoxLayout()
            layout.addWidget(self.staleness_label)
            layout.addWidget(QLabel("AI / Deterministic Output"))
            layout.addWidget(self.top_pane, stretch=1)
            layout.addLayout(top_buttons)
            layout.addWidget(QLabel("User / Used Context (sent to every other AI tool)"))
            layout.addWidget(self.bottom_pane, stretch=1)
            layout.addLayout(bottom_buttons)
            self.setLayout(layout)

            self._refresh()

        # -- View interface --------------------------------------------------

        def getData(self):
            return self.bv

        def getCurrentOffset(self):
            return 0

        def navigate(self, addr):
            return False

        def getFont(self):
            return ui.getMonospaceFont(self)

        # -- content -----------------------------------------------------

        def _refresh(self):
            top_text = get_enhancer_output(self.bv)
            if top_text is None:
                top_text = build_baseline(self.bv) or "(no deterministic evidence recorded yet -- " \
                    "run a framework/detector, or click Quick Enhance / Run Full Analysis)"
            self.top_pane.setPlainText(top_text)
            self.bottom_pane.setPlainText(get_user_edit(self.bv) or "")

            stale = is_stale(self.bv)
            if stale:
                self.staleness_label.setText(
                    "⚠ evidence has changed since the last enhancer run -- consider re-running"
                )
            else:
                self.staleness_label.setText("")

        def _set_busy(self, busy, label=None):
            for btn in self._action_buttons:
                btn.setEnabled(not busy)
            if busy and label:
                self.top_pane.setPlainText(label)

        def _on_quick_enhance(self):
            self._set_busy(True, "Running quick enhance...")

            def on_complete(text):
                execute_on_main_thread(lambda: (self._set_busy(False), self._refresh()))

            api.run_quick_enhance(self.bv, async_run=True, on_complete=on_complete)

        def _on_full_analysis(self):
            self._set_busy(True, "Running full analysis (agent)...")

            def on_complete(result):
                text, error = result
                if error:
                    logger.warning(f"Agentic Triage: full analysis failed: {error}")
                execute_on_main_thread(lambda: (self._set_busy(False), self._refresh()))

            api.run_agent_enhance(self.bv, async_run=True, on_complete=on_complete)

        def _on_copy_to_user_input(self):
            text = self.top_pane.toPlainText()
            self.bottom_pane.setPlainText(text)
            set_user_edit(self.bv, text)

        def _on_save_edit(self):
            set_user_edit(self.bv, self.bottom_pane.toPlainText())

        def _on_revert_edit(self):
            clear_user_edit(self.bv)
            self._refresh()

    return AgenticTriageView


class _AgenticTriageViewType:
    """Thin factory -- the real ViewType subclass is only constructed
    inside register_view_type() once binaryninjaui is confirmed
    importable, so this module has no import-time GUI dependency."""

    def __new__(cls):
        import binaryninjaui as ui

        view_class = _build_view_class()

        class _Impl(ui.ViewType):
            def __init__(self):
                super().__init__(_VIEW_NAME, _VIEW_LONG_NAME)

            def getPriority(self, data, filename):
                # Low, constant priority: available in the view-selector
                # dropdown, but never auto-selected as the default view
                # for any binary (unlike Linear/Graph/Triage).
                return 1

            def create(self, data, view_frame):
                return view_class(view_frame, data)

        return _Impl()
