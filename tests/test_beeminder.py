"""Beeminder push logic: which event types count, the guard branches, and the
datapoint payload (with ``requests`` mocked)."""
import copy

import requests

from backend import beeminder
from backend.config import DEFAULTS


def _cfg(**bm_over):
    cfg = copy.deepcopy(DEFAULTS)
    cfg["beeminder"].update(bm_over)
    return cfg


def test_counted_types_default():
    # default config counts approve/delete/repair, not send_back/exemplar
    assert beeminder.counted_types(_cfg()) == {"approve", "delete", "repair"}


def test_counted_types_send_back_and_exemplar():
    cfg = _cfg()
    cfg["beeminder"]["count"] = {
        "approve": False, "delete": False, "repair": False,
        "send_back": True, "exemplar": True,
    }
    assert beeminder.counted_types(cfg) == {"send_back", "exemplar_good", "exemplar_bad"}


def test_push_disabled_is_noop():
    assert beeminder.push_today(_cfg(enabled=False), 5) == {"pushed": False, "reason": "disabled"}


def test_push_enabled_but_unconfigured():
    cfg = _cfg(enabled=True, username="", auth_token="", goal="")
    assert beeminder.push_today(cfg, 5) == {"pushed": False, "reason": "unconfigured"}


def test_push_success_posts_expected_datapoint(monkeypatch):
    captured = {}

    class Resp:
        def raise_for_status(self):
            captured["raised"] = True

    def fake_post(url, data=None, timeout=None):
        captured["url"] = url
        captured["data"] = data
        return Resp()

    monkeypatch.setattr(requests, "post", fake_post)
    cfg = _cfg(enabled=True, username="me", auth_token="tok", goal="cards")
    out = beeminder.push_today(cfg, 7)

    assert out["pushed"] is True and out["value"] == 7
    assert "users/me/goals/cards/datapoints.json" in captured["url"]
    d = captured["data"]
    assert d["auth_token"] == "tok" and d["value"] == 7
    assert d["daystamp"] == out["daystamp"]
    assert d["requestid"] == "anki-workbench-%s" % out["daystamp"]  # idempotent per day
    assert captured["raised"] is True
