def register_setting(key, description, default, scope="user"):
    from binaryninja import Settings

    settings = Settings()
    if not settings.contains(key):
        settings.register_setting(key, description, default, scope=scope)
