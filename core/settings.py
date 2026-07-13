import json


def register_setting(key, description, default, scope="user"):
    from binaryninja import Settings

    settings = Settings()
    if settings.contains(key):
        return

    if isinstance(default, bool):
        setting_type = "boolean"
    elif isinstance(default, (int, float)):
        setting_type = "number"
    else:
        setting_type = "string"

    title = key.rsplit(".", 1)[-1].replace("_", " ").title()
    properties = {
        "title": title,
        "type": setting_type,
        "description": description,
        "default": default,
    }
    settings.register_setting(key, json.dumps(properties))
