class PluginError(Exception):
    pass


class AIConfigError(PluginError):
    pass


class AITimeoutError(PluginError):
    pass
