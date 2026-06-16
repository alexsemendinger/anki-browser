"""Beeminder push. The point of routing this through the tool is that the
number is measured, not self-reported, so there's nothing to fudge.

One aggregated datapoint per day, not one per card. requestid is the daystamp,
so repeated pushes on the same day update that day's point rather than piling
up new ones. What counts toward the value is configurable (see config beeminder.
count); queue size is deliberately never the metric.
"""
import requests
from datetime import datetime, timezone

API = "https://www.beeminder.com/api/v1"


def counted_types(cfg):
    count = cfg["beeminder"]["count"]
    types = set()
    if count.get("approve"):
        types.add("approve")
    if count.get("delete"):
        types.add("delete")
    if count.get("repair"):
        types.add("repair")
    if count.get("send_back"):
        types.add("send_back")
    if count.get("exemplar"):
        types.update({"exemplar_good", "exemplar_bad"})
    return types


def push_today(cfg, value):
    bm = cfg["beeminder"]
    if not bm["enabled"]:
        return {"pushed": False, "reason": "disabled"}
    if not (bm["username"] and bm["auth_token"] and bm["goal"]):
        return {"pushed": False, "reason": "unconfigured"}
    daystamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    url = "%s/users/%s/goals/%s/datapoints.json" % (
        API,
        bm["username"],
        bm["goal"],
    )
    resp = requests.post(
        url,
        data={
            "auth_token": bm["auth_token"],
            "value": value,
            "daystamp": daystamp,
            "requestid": "anki-workbench-%s" % daystamp,
            "comment": "anki-workbench auto",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return {"pushed": True, "value": value, "daystamp": daystamp}
