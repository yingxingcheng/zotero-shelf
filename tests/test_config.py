import json
import os
import stat

import pytest

from zotero_shelf import config
from zotero_shelf.errors import ShelfError


def test_atomic_private_settings(tmp_path):
    path = tmp_path / "settings/config.json"
    config.private_json(path, {"api_key": "DUMMY", "library_id": "123"})
    assert config.read_json(path)["api_key"] == "DUMMY"
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert not list(path.parent.glob(".settings-*"))


def test_environment_and_status_do_not_expose_key(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setenv("ZOTERO_LIBRARY_ID", "123")
    monkeypatch.setenv("ZOTERO_API_KEY", "SECRET-TEST-KEY")
    assert config.library_settings(path)["api_key"] == "SECRET-TEST-KEY"
    result = config.status(path, tmp_path / "webdav.json")
    assert result["api_key_configured"]
    assert "SECRET-TEST-KEY" not in json.dumps(result)


def test_invalid_configuration_does_not_echo_secrets(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"api_key": "DO-NOT-ECHO', encoding="utf-8")
    with pytest.raises(ShelfError) as error:
        config.read_json(path)
    assert "DO-NOT-ECHO" not in str(error.value)


def test_legacy_settings_read_without_copying(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Path, "home", lambda: tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "new-config"))
    legacy = tmp_path / ".config/zotero-api/config.json"
    config.private_json(legacy, {"library_id": "123"})
    assert config.resolve_path("library") == legacy
    destination = config.resolve_path("library", writing=True)
    assert destination == tmp_path / "new-config/zotero-shelf/config.json"
    assert not destination.exists()
