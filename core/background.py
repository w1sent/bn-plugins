import threading
from functools import wraps


def run_background_task(name, target, on_complete=None, on_error=None):
    def wrapper():
        try:
            result = target()
            if on_complete:
                on_complete(result)
        except Exception as exc:
            if on_error:
                on_error(exc)
            else:
                import traceback
                traceback.print_exc()

    thread = threading.Thread(target=wrapper, name=name, daemon=True)
    thread.start()
    return thread
