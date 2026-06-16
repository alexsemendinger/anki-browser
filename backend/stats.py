"""Lightweight stats. Append one event per judgment; derive everything else.

Event types: approve, delete, send_back, repair, exemplar_good, exemplar_bad.
"""
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone

PROCESSED = {"approve", "delete", "repair"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def record(stats_file, event_type):
    row = {"ts": _now(), "type": event_type}
    with open(stats_file, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    return row


def pop_last(stats_file):
    rows = _read(stats_file)
    if not rows:
        return None
    last = rows.pop()
    with open(stats_file, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return last


def _read(stats_file):
    if not os.path.exists(stats_file):
        return []
    out = []
    with open(stats_file, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _day(ts):
    return ts[:10]


def count_today(stats_file, types):
    today = datetime.now(timezone.utc).isoformat()[:10]
    return sum(
        1 for r in _read(stats_file) if _day(r["ts"]) == today and r["type"] in types
    )


def summary(stats_file):
    rows = _read(stats_file)
    totals = Counter(r["type"] for r in rows)
    processed = sum(totals[t] for t in PROCESSED)
    approve = totals["approve"]
    decided = totals["approve"] + totals["delete"]
    approval_rate = round(approve / decided, 3) if decided else None

    per_day = defaultdict(Counter)
    for row in rows:
        per_day[_day(row["ts"])][row["type"]] += 1
    daily = []
    for day in sorted(per_day):
        c = per_day[day]
        decided_d = c["approve"] + c["delete"]
        daily.append(
            {
                "day": day,
                "approve": c["approve"],
                "delete": c["delete"],
                "send_back": c["send_back"],
                "repair": c["repair"],
                "processed": sum(c[t] for t in PROCESSED),
                "approval_rate": round(c["approve"] / decided_d, 3)
                if decided_d
                else None,
            }
        )

    return {
        "processed_lifetime": processed,
        "approval_rate": approval_rate,
        "totals": dict(totals),
        "inflow_vs_repair": {
            "inflow_approved": approve,
            "repairs": totals["repair"],
        },
        "judgments": totals["approve"]
        + totals["delete"]
        + totals["send_back"]
        + totals["exemplar_good"]
        + totals["exemplar_bad"],
        "daily": daily,
    }
