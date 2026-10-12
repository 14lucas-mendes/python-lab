import importlib
import importlib.util
from dataclasses import FrozenInstanceError

import pytest

from python_lab.assistant.errors import AssistantError


def settings_module():
    assert importlib.util.find_spec("python_lab.assistant.settings") is not None, "B3 settings missing"
    return importlib.import_module("python_lab.assistant.settings")


def test_missing_configuration_disables_only_assistant(tmp_path):
    settings = settings_module().load_settings(tmp_path)
    assert settings.provider == "disabled"
    assert settings.model is None
    assert (settings.timeout_seconds, settings.max_output_tokens, settings.max_session_output_tokens) == (30, 2000, 20000)
    assert list(tmp_path.iterdir()) == []


def test_explicit_top_level_toml_and_immutable_settings(tmp_path):
    (tmp_path / "config.toml").write_text('provider="openai"\nmodel="user-selected-model"\ntimeout_seconds=12\nmax_output_tokens=100\nmax_session_output_tokens=300\n')
    settings = settings_module().load_settings(tmp_path)
    assert settings == settings_module().AssistantSettings("openai", "user-selected-model", 12, 100, 300)
    with pytest.raises(FrozenInstanceError):
        settings.model = "other"


def test_missing_model_has_no_invented_default(tmp_path):
    (tmp_path / "config.toml").write_text('provider="openai"\n')
    assert settings_module().load_settings(tmp_path).model is None


@pytest.mark.parametrize("contents", ["", 'model="SECRET-DO-NOT-ECHO"\n', "max_output_tokens=100\n"])
def test_present_config_requires_explicit_provider(tmp_path, contents, caplog):
    (tmp_path / "config.toml").write_text(contents)
    with pytest.raises(AssistantError, match="provider") as caught:
        settings_module().load_settings(tmp_path)
    assert "SECRET-DO-NOT-ECHO" not in str(caught.value) + caplog.text


@pytest.mark.parametrize("field", ["timeout_seconds", "max_output_tokens", "max_session_output_tokens"])
@pytest.mark.parametrize("value", [-1, 0, True, 1.5, "30", None])
def test_config_rejects_invalid_numeric_values(field, value):
    with pytest.raises(AssistantError):
        settings_module().AssistantSettings("openai", "chosen", **{field: value})


@pytest.mark.parametrize("provider,model", [("other", "chosen"), (True, "chosen"), ("openai", ""), ("openai", "  "), ("openai", 5)])
def test_config_rejects_invalid_provider_and_model(provider, model):
    with pytest.raises(AssistantError):
        settings_module().AssistantSettings(provider, model)


@pytest.mark.parametrize("contents", [
    'provider="SECRET-DO-NOT-ECHO"\n',
    'provider="openai"\nLAB_API_KEY="SECRET-DO-NOT-ECHO"\n',
    'model="SECRET-DO-NOT-ECHO\n',
    '[assistant]\nprovider="openai"\n',
])
def test_config_errors_do_not_echo_values_or_secrets(tmp_path, contents, caplog):
    (tmp_path / "config.toml").write_text(contents)
    with pytest.raises(AssistantError) as caught:
        settings_module().load_settings(tmp_path)
    assert "SECRET-DO-NOT-ECHO" not in str(caught.value) + caplog.text
    assert caught.value.__cause__ is None


def test_read_failure_is_application_error(tmp_path):
    (tmp_path / "config.toml").mkdir()
    with pytest.raises(AssistantError, match="config.toml"):
        settings_module().load_settings(tmp_path)
