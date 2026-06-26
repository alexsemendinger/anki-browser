import os

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


def test_stats_exemplars_count_as_judgments_not_processed(cfg):
    f = cfg["paths"]["stats"]
    for t in ["approve", "delete", "exemplar_good", "exemplar_bad"]:
        stats.record(f, t)
    s = stats.summary(f)
    assert s["judgments"] == 4               # approve + delete + 2 exemplars
    assert s["processed_lifetime"] == 2      # only approve + delete are "processing"
    assert len(s["daily"]) == 1


def test_stats_pop_last_empty_is_none(cfg):
    assert stats.pop_last(cfg["paths"]["stats"]) is None


def test_stats_count_today_filters_type(cfg):
    f = cfg["paths"]["stats"]
    stats.record(f, "approve")
    stats.record(f, "delete")
    assert stats.count_today(f, {"approve"}) == 1
    assert stats.count_today(f, {"approve", "delete"}) == 2


def test_inbox_skips_malformed_file(cfg):
    d = cfg["paths"]["inbox"]
    inbox.save_card(d, {"id": "good", "fields": {"Front": "x"}})
    with open(os.path.join(d, "broken.json"), "w", encoding="utf-8") as fh:
        fh.write("{ not valid json")
    cards = inbox.list_cards(d)
    assert [c["id"] for c in cards] == ["good"]  # malformed skipped, not raised


def test_inbox_set_approved_dedupes_and_sorts(cfg):
    d = cfg["paths"]["inbox"]
    inbox.save_card(d, {"id": "x", "fields": {}})
    inbox.set_approved(d, "x", [2, 1, 1])
    assert inbox.get_card(d, "x")["approved_cards"] == [1, 2]


def test_inbox_missing_card_helpers_return_none(cfg):
    d = cfg["paths"]["inbox"]
    assert inbox.get_card(d, "nope") is None
    assert inbox.update_fields(d, "nope", {}) is None
    assert inbox.remove_card(d, "nope") is None
    assert inbox.set_approved(d, "nope", [1]) is None
    assert inbox.add_comment(d, "nope", "x") is None


def test_inbox_normalize_defaults(cfg):
    d = cfg["paths"]["inbox"]
    card = inbox.save_card(d, {"fields": {"Front": "x"}})
    got = inbox.get_card(d, card["id"])
    assert got["note_type"] == "Basic" and got["deck"] == "Default"
    assert got["source"] == "manual" and got["approved_cards"] == []
    assert got["comment_history"] == []


def test_graveyard_list_sorted_newest_first(cfg):
    g = cfg["paths"]["graveyard"]
    graveyard.bury(g, {"id": "old", "fields": {}}, origin="inbox")
    graveyard.bury(g, {"id": "new", "fields": {}}, origin="inbox")
    buried = graveyard.list_buried(g)
    assert len(buried) == 2
    assert buried[0]["buried"] >= buried[1]["buried"]  # newest first


def test_actions_stack(cfg):
    f = cfg["paths"]["actions"]
    actions.push(f, "approve", {"x": 1}, "approve")
    actions.push(f, "delete", {"y": 2}, "delete")
    assert actions.depth(f) == 2
    assert actions.peek(f)["kind"] == "delete"
    popped = actions.pop(f)
    assert popped["kind"] == "delete"
    assert actions.depth(f) == 1


def test_exemplars_pop_last_empty_is_none(cfg):
    assert exemplars.pop_last(cfg["paths"]["exemplars"]) is None
    assert exemplars.list_all(cfg["paths"]["exemplars"]) == []


def test_stats_pop_last_removes_top(cfg):
    f = cfg["paths"]["stats"]
    stats.record(f, "approve")
    stats.record(f, "delete")
    assert stats.pop_last(f)["type"] == "delete"
    assert [r["type"] for r in stats._read(f)] == ["approve"]
