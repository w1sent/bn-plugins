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
        # Per BN's own Settings docs: settings that "impact analysis" get
        # their effective (Default/User/Project) value snapshotted into
        # Resource scope -- the highest-preference scope -- the first time
        # a BinaryView is analyzed, so the analysis stays reproducible if
        # Default/User/Project settings change later. Resource then
        # permanently shadows later User-scope edits for that already-
        # analyzed binary/BNDB. None of our AI-plugin settings (provider,
        # mode, thresholds, etc.) affect BN's own analysis -- they only
        # affect this plugin's runtime behavior -- so without this, editing
        # a setting in BN's Settings dialog after a binary's first analysis
        # appears to do nothing on subsequent runs against that binary.
        "ignore": ["SettingsProjectScope", "SettingsResourceScope"],
    }
    settings.register_setting(key, json.dumps(properties))
