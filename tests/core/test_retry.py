from core.retry import retry_with_backoff
from core.exceptions import AIConfigError, AITimeoutError


def test_retry_succeeds_on_first_attempt():
    calls = []
    def fn():
        calls.append(1)
        return "ok"
    result = retry_with_backoff(fn, backoff_steps=[1, 2])
    assert result == "ok"
    assert len(calls) == 1


def test_retry_retries_on_failure():
    calls = []
    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("not yet")
        return "ok"
    result = retry_with_backoff(fn, backoff_steps=[0.01, 0.01, 0.01])
    assert result == "ok"
    assert len(calls) == 3


def test_retry_raises_after_exhausting_attempts():
    calls = []
    def fn():
        calls.append(1)
        raise ValueError("always fails")
    try:
        retry_with_backoff(fn, backoff_steps=[0.01, 0.01])
        assert False, "expected ValueError"
    except ValueError:
        assert len(calls) == 2


def test_retry_does_not_retry_ai_config_error():
    calls = []
    def fn():
        calls.append(1)
        raise AIConfigError("bad config")
    try:
        retry_with_backoff(fn, backoff_steps=[0.01, 0.01])
        assert False, "expected AIConfigError"
    except AIConfigError:
        assert len(calls) == 1


def test_retry_retries_ai_timeout():
    calls = []
    def fn():
        calls.append(1)
        if len(calls) < 2:
            raise AITimeoutError("timed out")
        return "ok"
    result = retry_with_backoff(fn, backoff_steps=[0.01, 0.01])
    assert result == "ok"
    assert len(calls) == 2


def test_retry_calls_on_warning():
    warnings = []
    def fn():
        raise ValueError("fail")
    def on_warning(attempt, exc):
        warnings.append((attempt, str(exc)))
    try:
        retry_with_backoff(fn, backoff_steps=[0.01, 0.01, 0.01], on_warning=on_warning)
    except ValueError:
        pass
    assert len(warnings) == 2


def test_retry_calls_on_failure():
    failures = []
    def fn():
        raise ValueError("fail")
    def on_failure(exc):
        failures.append(str(exc))
    try:
        retry_with_backoff(fn, backoff_steps=[0.01], on_failure=on_failure)
    except ValueError:
        pass
    assert failures == ["fail"]


def test_retry_passes_args_and_kwargs():
    seen = []
    def fn(a, b=None):
        seen.append((a, b))
        return a + b
    result = retry_with_backoff(fn, args=(1,), kwargs={"b": 2}, backoff_steps=[0.01])
    assert result == 3
    assert seen == [(1, 2)]
