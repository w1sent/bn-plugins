import json
from pathlib import Path


def create_json_file_if_missing(path, defaults):
    """Write `defaults` to `path` as JSON if nothing exists there yet.

    Returns True if the file was created, False if it already existed.
    """
    path = Path(path)
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(defaults, indent=2) + "\n")
    return True


def load_or_create_json_config(path, defaults):
    """Load a JSON config file, creating it with `defaults` if missing.

    Existing files are merged with `defaults` shallowly -- top-level keys
    absent from the file fall back to the default value -- so adding a new
    default key to a plugin doesn't require users to hand-edit an existing
    config file. Callers needing a deeper merge (e.g. per-provider nested
    keys) should call `create_json_file_if_missing` themselves and do their
    own merge on top of it -- see `ai_config.load_ai_config`.
    """
    path = Path(path)
    if create_json_file_if_missing(path, defaults):
        return json.loads(json.dumps(defaults))

    with open(path) as f:
        user_config = json.load(f)

    config = json.loads(json.dumps(defaults))
    config.update(user_config)
    return config
