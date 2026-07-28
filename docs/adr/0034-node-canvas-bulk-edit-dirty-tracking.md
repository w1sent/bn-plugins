# node-canvas bulk edit: apply only fields the user actually touched

Selecting several nodes or edges and editing shared attributes (color, edge
style/routing, ...) needs "leave whatever you didn't touch alone" semantics
-- e.g. changing border color for a multi-selection of nodes must not also
collapse their different fill colors down to one value. A value-comparison
approach (diff the dialog's final values against each entity's own current
value) can't express this per-field, since `FormDialog` shows one seeded
value for a field the whole selection may disagree on.

Instead `FormDialog` gained `track_dirty`: each field's Qt change signal is
connected to a handler that just records the field's key as touched,
independent of what value it ends up at. `changed_values()` (used via the
new `FormDialog.get_changed()`) returns only the touched fields; the bulk
actions (`_action_bulk_edit_nodes`, `_action_bulk_edit_edges`) then apply
only those keys across every selected entity, leaving the rest of each
entity's state as it was. Selection-disagreement is shown to the user via a
"(mixed)" label suffix and, for choice fields, a synthetic "(mixed)" option
-- but the user never has to explicitly reselect a per-item value to leave
it alone, since simply not touching the widget already does that.

**Considered and rejected:**
- Per-field tri-state widgets (e.g. tri-state checkboxes) -- more UI
  plumbing per field kind, whereas dirty-tracking is one mechanism that
  works uniformly across text/color/choice/checkbox/spinbox fields.
- Comparing submitted values against a seeded "common or blank" value --
  ambiguous for fields where blank is itself a meaningful value (e.g. color
  "blank = default" already means something in the single-entity Edit
  dialogs), and wrongly signals "changed" if the user's edit happens to
  land back on the seeded value.
