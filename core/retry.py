import time

from .exceptions import AIConfigError


def retry_with_backoff(
    fn,
    args=None,
    kwargs=None,
    backoff_steps=None,
    on_warning=None,
    on_failure=None,
):
    args = args or ()
    kwargs = kwargs or {}
    backoff_steps = backoff_steps or [1, 2, 4, 8]
    last_exc = None

    for attempt, delay in enumerate(backoff_steps):
        try:
            return fn(*args, **kwargs)
        except AIConfigError:
            raise
        except Exception as exc:
            last_exc = exc
            if attempt < 2 and on_warning:
                on_warning(attempt + 1, exc)
            if attempt == len(backoff_steps) - 1:
                if on_failure:
                    on_failure(exc)
                raise
            time.sleep(delay)

    raise last_exc
