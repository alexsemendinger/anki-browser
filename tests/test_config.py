"""Config loading: defaults, deep merge of user config.json, path computation,
and secret stripping for the frontend."""
import json
import os

from backend import config as config_mod


def _load(tmp_path, user):
    user = {"data_dir": str(tmp_path / "data"), **user}
    p = tmp_path / "config.json"
    p.write_text(json.dumps(user))
    return config_mod.load_config(str(p))


def test_defaults_present_and_dirs_created(tmp_path):
    cfg = _load(tmp_path, {})
    assert cfg["default_deck"] == "Default"
    assert cfg["ankiconnect_url"].endswith(":8765")
    for key in ("data", "inbox", "graveyard"):
        assert os.path.isdir(cfg["paths"][key])


def test_user_config_deep_merges(tmp_path):
    cfg = _load(tmp_path, {
        "default_deck": "MyDeck",
        "beeminder": {"enabled": True, "username": "u"},
    })
    assert cfg["default_deck"] == "MyDeck"
    assert cfg["beeminder"]["enabled"] is True and cfg["beeminder"]["username"] == "u"
    # untouched nested defaults survive the merge
    assert cfg["beeminder"]["count"]["approve"] is True
    assert cfg["beeminder"]["push_on"] == "session_end"


def test_absolute_data_dir_respected(tmp_path):
    d = tmp_path / "custom-data"
    cfg = config_mod.load_config(str(_write(tmp_path, {"data_dir": str(d)})))
    assert cfg["paths"]["data"] == str(d)


def test_public_config_strips_secrets(tmp_path):
    cfg = _load(tmp_path, {"beeminder": {"enabled": True, "auth_token": "SECRET", "goal": "g"}})
    pub = config_mod.public_config(cfg)
    assert pub["beeminder"] == {"enabled": True, "goal": "g"}
    assert "auth_token" not in pub["beeminder"] and "username" not in pub["beeminder"]
    assert pub["default_deck"] == "Default"


def _write(tmp_path, user):
    p = tmp_path / "config.json"
    p.write_text(json.dumps(user))
    return p
