import json
from pathlib import Path


def load_or_create_json_config(path, defaults):
    """Load a JSON config file, creating it with `defaults` if missing.

    Existing files are merged with `defaults` shallowly -- top-level keys
    absent from the file fall back to the default value -- so adding a new
    default key to a plugin doesn't require users to hand-edit an existing
    config file.
    """
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(defaults, indent=2) + "\n")
        return json.loads(json.dumps(defaults))

    with open(path) as f:
        user_config = json.load(f)

    config = json.loads(json.dumps(defaults))
    config.update(user_config)
    return config
