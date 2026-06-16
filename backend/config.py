"""Config loading. Defaults merged with optional config.json at project root."""
import copy
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULTS = {
    "ankiconnect_url": "http://127.0.0.1:8765",
    "ankiconnect_version": 6,
    "data_dir": "data",
    "default_deck": "Default",
    "repair_flags": [1, 2],
    "grid_show_backs": True,
    "grid_mathjax": True,
    "mathjax_url": "https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js",
    "send_back_requires_comment": False,
    "session": {
        "target_enabled": False,
        "target_default": 10,
    },
    "beeminder": {
        "enabled": False,
        "username": "",
        "auth_token": "",
        "goal": "",
        "push_on": "session_end",
        "count": {
            "approve": True,
            "delete": True,
            "repair": True,
            "send_back": False,
            "exemplar": False,
        },
    },
}


def _deep_merge(base, override):
    out = copy.deepcopy(base)
    for key, val in (override or {}).items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def load_config(path=None):
    path = path or os.path.join(ROOT, "config.json")
    user = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            user = json.load(fh)
    cfg = _deep_merge(DEFAULTS, user)
    cfg["_root"] = ROOT
    data_dir = cfg["data_dir"]
    if not os.path.isabs(data_dir):
        data_dir = os.path.join(ROOT, data_dir)
    cfg["paths"] = {
        "data": data_dir,
        "inbox": os.path.join(data_dir, "inbox"),
        "graveyard": os.path.join(data_dir, "graveyard"),
        "exemplars": os.path.join(data_dir, "exemplars.jsonl"),
        "stats": os.path.join(data_dir, "events.jsonl"),
        "actions": os.path.join(data_dir, "actions.json"),
        "session": os.path.join(data_dir, "session.json"),
    }
    for key in ("data", "inbox", "graveyard"):
        os.makedirs(cfg["paths"][key], exist_ok=True)
    return cfg


def public_config(cfg):
    """Config safe to hand the frontend. Strips secrets."""
    bm = cfg["beeminder"]
    return {
        "default_deck": cfg["default_deck"],
        "repair_flags": cfg["repair_flags"],
        "grid_show_backs": cfg["grid_show_backs"],
        "grid_mathjax": cfg["grid_mathjax"],
        "mathjax_url": cfg["mathjax_url"],
        "send_back_requires_comment": cfg["send_back_requires_comment"],
        "session": cfg["session"],
        "beeminder": {"enabled": bm["enabled"], "goal": bm["goal"]},
    }
