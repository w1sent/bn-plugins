import threading
import time

from core.background import run_background_task


def test_background_task_runs():
    results = []
    def target():
        results.append("done")
    thread = run_background_task("test", target)
    thread.join(timeout=2)
    assert results == ["done"]


def test_background_task_calls_on_complete():
    completed = []
    def target():
        return 42
    def on_complete(result):
        completed.append(result)
    thread = run_background_task("test", target, on_complete=on_complete)
    thread.join(timeout=2)
    assert completed == [42]


def test_background_task_calls_on_error():
    errors = []
    def target():
        raise ValueError("boom")
    def on_error(exc):
        errors.append(str(exc))
    thread = run_background_task("test", target, on_error=on_error)
    thread.join(timeout=2)
    assert errors == ["boom"]


def test_background_task_is_daemon():
    def target():
        pass
    thread = run_background_task("test", target)
    assert thread.daemon is True


def test_background_task_has_name():
    def target():
        pass
    thread = run_background_task("my_task", target)
    assert thread.name == "my_task"
