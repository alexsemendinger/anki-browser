from backend import actions, exemplars, graveyard, inbox, stats


def test_inbox_roundtrip(cfg):
    d = cfg["paths"]["inbox"]
    card = inbox.save_card(d, {"fields": {"Front": "a", "Back": "b"}})
    assert card["id"]
    assert inbox.count(d) == 1
    got = inbox.get_card(d, card["id"])
    assert got["fields"]["Front"] == "a"
    inbox.add_comment(d, card["id"], "fix this")
    assert inbox.get_card(d, card["id"])["comment_history"][0]["text"] == "fix this"
    inbox.pop_comment(d, card["id"])
    assert inbox.get_card(d, card["id"])["comment_history"] == []
    removed = inbox.remove_card(d, card["id"])
    assert removed["id"] == card["id"]
    assert inbox.count(d) == 0


def test_inbox_update_fields(cfg):
    d = cfg["paths"]["inbox"]
    card = inbox.save_card(d, {"fields": {"Front": "a"}})
    inbox.update_fields(d, card["id"], {"Front": "z"})
    assert inbox.get_card(d, card["id"])["fields"]["Front"] == "z"


def test_graveyard_roundtrip(cfg):
    g = cfg["paths"]["graveyard"]
    card = {"id": "abc", "fields": {"Front": "x"}}
    graveyard.bury(g, card, origin="inbox")
    assert len(graveyard.list_buried(g)) == 1
    back = graveyard.exhume(g, "abc")
    assert back["fields"]["Front"] == "x"
    assert graveyard.exhume(g, "abc") is None


def test_exemplars_append_only(cfg):
    f = cfg["paths"]["exemplars"]
    exemplars.add(f, verdict="good", fields={"Front": "a"}, rendered={}, note_type="Basic")
    exemplars.add(f, verdict="bad", fields={"Front": "b"}, rendered={}, note_type="Basic")
    rows = exemplars.list_all(f)
    assert [r["verdict"] for r in rows] == ["good", "bad"]
    popped = exemplars.pop_last(f)
    assert popped["verdict"] == "bad"
    assert len(exemplars.list_all(f)) == 1


def test_stats_summary(cfg):
    f = cfg["paths"]["stats"]
    for t in ["approve", "approve", "delete", "send_back", "repair"]:
        stats.record(f, t)
    s = stats.summary(f)
    assert s["totals"]["approve"] == 2
    assert s["processed_lifetime"] == 4  # 2 approve + 1 delete + 1 repair
    assert s["approval_rate"] == round(2 / 3, 3)  # 2 approve of 3 decided
    assert stats.count_today(f, {"approve"}) == 2


def test_actions_stack(cfg):
    f = cfg["paths"]["actions"]
    actions.push(f, "approve", {"x": 1}, "approve")
    actions.push(f, "delete", {"y": 2}, "delete")
    assert actions.depth(f) == 2
    assert actions.peek(f)["kind"] == "delete"
    popped = actions.pop(f)
    assert popped["kind"] == "delete"
    assert actions.depth(f) == 1
