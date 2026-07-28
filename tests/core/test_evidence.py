from core.evidence import get_all_evidence, get_evidence, latest_last_run, record_evidence


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


def test_record_and_get_evidence():
    bv = FakeBV()
    record_evidence(bv, "flutter", [{"claim": "Flutter detected"}], last_run="2026-01-01T00:00:00+00:00")

    entry = get_evidence(bv, "flutter")
    assert entry["findings"] == [{"claim": "Flutter detected"}]
    assert entry["last_run"] == "2026-01-01T00:00:00+00:00"


def test_get_evidence_missing_detector_returns_none():
    bv = FakeBV()
    assert get_evidence(bv, "flutter") is None


def test_rerunning_one_detector_does_not_touch_others():
    bv = FakeBV()
    record_evidence(bv, "flutter", ["a"], last_run="2026-01-01T00:00:00+00:00")
    record_evidence(bv, "dotnet_native_aot", ["b"], last_run="2026-01-01T00:00:00+00:00")

    record_evidence(bv, "flutter", ["a-updated"], last_run="2026-01-02T00:00:00+00:00")

    assert get_evidence(bv, "flutter")["findings"] == ["a-updated"]
    assert get_evidence(bv, "dotnet_native_aot")["findings"] == ["b"]


def test_get_all_evidence_scans_by_prefix_only():
    bv = FakeBV()
    record_evidence(bv, "flutter", ["a"], last_run="2026-01-01T00:00:00+00:00")
    bv.store_metadata("node_canvas.canvases", {"unrelated": True})

    all_evidence = get_all_evidence(bv)
    assert set(all_evidence.keys()) == {"flutter"}


def test_latest_last_run_returns_max_across_detectors():
    bv = FakeBV()
    record_evidence(bv, "flutter", ["a"], last_run="2026-01-01T00:00:00+00:00")
    record_evidence(bv, "dotnet_native_aot", ["b"], last_run="2026-03-01T00:00:00+00:00")

    assert latest_last_run(bv) == "2026-03-01T00:00:00+00:00"


def test_latest_last_run_none_when_empty():
    bv = FakeBV()
    assert latest_last_run(bv) is None


def test_record_evidence_defaults_last_run_to_now():
    bv = FakeBV()
    record_evidence(bv, "flutter", ["a"])
    assert get_evidence(bv, "flutter")["last_run"]
