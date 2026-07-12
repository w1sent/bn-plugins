from core.exceptions import PluginError, AIConfigError, AITimeoutError


def test_plugin_error_is_exception():
    assert issubclass(PluginError, Exception)


def test_ai_config_error_is_plugin_error():
    assert issubclass(AIConfigError, PluginError)


def test_ai_timeout_error_is_plugin_error():
    assert issubclass(AITimeoutError, PluginError)


def test_plugin_error_can_be_raised():
    try:
        raise PluginError("test error")
    except PluginError as e:
        assert str(e) == "test error"


def test_ai_config_error_can_be_raised():
    try:
        raise AIConfigError("bad config")
    except PluginError as e:
        assert str(e) == "bad config"


def test_ai_timeout_error_can_be_raised():
    try:
        raise AITimeoutError("timed out")
    except PluginError as e:
        assert str(e) == "timed out"
