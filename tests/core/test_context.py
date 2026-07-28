from core.context import (
    build_baseline,
    clear_user_edit,
    get_context_prompt,
    get_enhancer_output,
    get_user_edit,
    is_stale,
    record_enhancer_output,
    set_user_edit,
)
from core.evidence import record_evidence


class FakeBV:
    def __init__(self):
        self._store = {}

    def store_metadata(self, key, value):
        self._store[key] = value

    def get_metadata(self, key, default=None):
        return self._store.get(key, default)

    @property
    def metadata(self):
        return dict(self._store)


def test_build_baseline_empty_with_no_evidence():
    bv = FakeBV()
    assert build_baseline(bv) == ""


def test_build_baseline_renders_evidence_findings():
    bv = FakeBV()
    record_evidence(bv, "flutter", ["Flutter engine detected"], last_run="2026-01-01T00:00:00+00:00")

    baseline = build_baseline(bv)
    assert "[flutter] Flutter engine detected" in baseline


def test_context_prompt_falls_back_to_baseline():
    bv = FakeBV()
    record_evidence(bv, "flutter", ["Flutter engine detected"], last_run="2026-01-01T00:00:00+00:00")

    assert get_context_prompt(bv) == build_baseline(bv)


def test_context_prompt_prefers_enhancer_output_over_baseline():
    bv = FakeBV()
    record_evidence(bv, "flutter", ["Flutter engine detected"], last_run="2026-01-01T00:00:00+00:00")
    record_enhancer_output(bv, "This is a Flutter app targeting Android.", last_run="2026-01-02T00:00:00+00:00")

    assert get_context_prompt(bv) == "This is a Flutter app targeting Android."


def test_context_prompt_prefers_user_edit_over_enhancer_output():
    bv = FakeBV()
    record_enhancer_output(bv, "AI summary", last_run="2026-01-02T00:00:00+00:00")
    set_user_edit(bv, "My corrected summary")

    assert get_context_prompt(bv) == "My corrected summary"
    assert get_enhancer_output(bv) == "AI summary"


def test_rerunning_enhancer_does_not_touch_user_edit():
    bv = FakeBV()
    set_user_edit(bv, "My corrected summary")
    record_enhancer_output(bv, "new AI summary", last_run="2026-02-01T00:00:00+00:00")

    assert get_user_edit(bv) == "My corrected summary"
    assert get_context_prompt(bv) == "My corrected summary"


def test_clear_user_edit_reverts_to_enhancer_output():
    bv = FakeBV()
    record_enhancer_output(bv, "AI summary", last_run="2026-01-02T00:00:00+00:00")
    set_user_edit(bv, "My corrected summary")

    clear_user_edit(bv)

    assert get_user_edit(bv) is None
    assert get_context_prompt(bv) == "AI summary"


def test_is_stale_none_when_enhancer_never_ran():
    bv = FakeBV()
    record_evidence(bv, "flutter", ["a"], last_run="2026-01-01T00:00:00+00:00")
    assert is_stale(bv) is None


def test_is_stale_false_when_enhancer_is_newer_than_evidence():
    bv = FakeBV()
    record_evidence(bv, "flutter", ["a"], last_run="2026-01-01T00:00:00+00:00")
    record_enhancer_output(bv, "summary", last_run="2026-01-02T00:00:00+00:00")

    assert is_stale(bv) is False


def test_is_stale_true_when_evidence_rerun_after_enhancer():
    bv = FakeBV()
    record_enhancer_output(bv, "summary", last_run="2026-01-01T00:00:00+00:00")
    record_evidence(bv, "flutter", ["a-updated"], last_run="2026-01-02T00:00:00+00:00")

    assert is_stale(bv) is True
