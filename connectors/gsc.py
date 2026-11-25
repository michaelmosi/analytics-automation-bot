"""Google Search Console connector: clicks, impressions and position by date, query and page.

Config (JSON):
    {"type": "gsc", "name": "gsc", "site": "sc-domain:example.com"}      # live, via the Search Console API
    {"type": "gsc", "name": "gsc", "csv": "samples/gsc.sample.csv"}      # offline, from an export

CSV columns: date, query, page, clicks, impressions, position

Live mode needs:  pip install google-api-python-client google-auth
and GOOGLE_APPLICATION_CREDENTIALS for a service account that has been added as a user on the property.
"""
from . import in_range, num, read_csv, register, row, to_date

SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"


def build_request_body(start, end, start_row=0, row_limit=25000):
    return {"startDate": start.isoformat(), "endDate": end.isoformat(),
            "dimensions": ["date", "query", "page"], "rowLimit": row_limit, "startRow": start_row}


def _from_csv(cfg, start, end):
    out = []
    for r in read_csv(cfg["csv"]):
        day = to_date(r["date"])
        if in_range(day, start, end):
            out.append(row(day, cfg.get("name", "gsc"), channel="Organic Search", query=r.get("query", ""),
                           page=r.get("page", ""), clicks=num(r.get("clicks")),
                           impressions=num(r.get("impressions")), position=num(r.get("position"))))
    return out


def _from_api(cfg, start, end):
    try:
        import google.auth
        from googleapiclient.discovery import build
    except ImportError:
        raise SystemExit("Search Console live mode needs:  pip install google-api-python-client google-auth")
    creds, _ = google.auth.default(scopes=[SCOPE])
    service = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
    out, start_row = [], 0
    while True:
        body = build_request_body(start, end, start_row)
        rows = service.searchanalytics().query(siteUrl=cfg["site"], body=body).execute().get("rows", [])
        for r in rows:
            day, query, page = r["keys"]
            out.append(row(to_date(day), cfg.get("name", "gsc"), channel="Organic Search", query=query, page=page,
                           clicks=r["clicks"], impressions=r["impressions"], position=r["position"]))
        if len(rows) < body["rowLimit"]:
            return out
        start_row += body["rowLimit"]


@register("gsc")
def fetch(cfg, start, end):
    return _from_csv(cfg, start, end) if cfg.get("csv") else _from_api(cfg, start, end)
