"""PostHog connector: daily users, pageviews and a conversion event, via a HogQL query.

Config (JSON):
    {"type": "posthog", "name": "posthog", "project_id": "12345", "conversion_event": "sign_up",
     "host": "https://us.posthog.com"}                                    # live, via the PostHog API
    {"type": "posthog", "name": "posthog", "csv": "samples/posthog.sample.csv"}   # offline, from an export

CSV columns: date, users, pageviews, conversions

Live mode uses only the standard library. Set POSTHOG_PERSONAL_API_KEY (a personal API key with
"Query: read" access, not the public project key). Use https://eu.posthog.com for EU projects.
"""
import json
import os
import re
import urllib.request

from . import in_range, num, read_csv, register, row, to_date

SAFE_EVENT = re.compile(r"^[A-Za-z0-9_$.\- ]+$")


def build_hogql(conversion_event, start, end):
    """HogQL for one row per day. The event name is validated, never string-trusted."""
    if not SAFE_EVENT.match(conversion_event):
        raise ValueError(f"unsafe conversion event name: {conversion_event!r}")
    return (
        "SELECT toDate(timestamp) AS day, count(DISTINCT person_id) AS users, "
        "countIf(event = '$pageview') AS pageviews, "
        f"countIf(event = '{conversion_event}') AS conversions "
        f"FROM events WHERE timestamp >= toDateTime('{start.isoformat()} 00:00:00') "
        f"AND timestamp < toDateTime('{end.isoformat()} 00:00:00') + INTERVAL 1 DAY "
        "GROUP BY day ORDER BY day"
    )


def _from_csv(cfg, start, end):
    out = []
    for r in read_csv(cfg["csv"]):
        day = to_date(r["date"])
        if in_range(day, start, end):
            out.append(row(day, cfg.get("name", "posthog"), users=num(r.get("users")),
                           pageviews=num(r.get("pageviews")), conversions=num(r.get("conversions"))))
    return out


def _from_api(cfg, start, end):
    key = os.environ.get("POSTHOG_PERSONAL_API_KEY")
    if not key:
        raise SystemExit("Set POSTHOG_PERSONAL_API_KEY to use PostHog live mode.")
    host = cfg.get("host", "https://us.posthog.com").rstrip("/")
    payload = {"query": {"kind": "HogQLQuery", "query": build_hogql(cfg.get("conversion_event", "sign_up"), start, end)}}
    req = urllib.request.Request(
        f"{host}/api/projects/{cfg['project_id']}/query/", data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        results = json.loads(resp.read()).get("results", [])
    return [row(to_date(day), cfg.get("name", "posthog"), users=num(u), pageviews=num(pv), conversions=num(c))
            for day, u, pv, c in results]


@register("posthog")
def fetch(cfg, start, end):
    return _from_csv(cfg, start, end) if cfg.get("csv") else _from_api(cfg, start, end)
