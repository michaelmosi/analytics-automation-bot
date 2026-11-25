"""GA4 connector: website sessions, users and key events by date, channel and page.

Config (JSON):
    {"type": "ga4", "name": "ga4", "property": "123456789"}            # live, via the GA4 Data API
    {"type": "ga4", "name": "ga4", "csv": "samples/ga4.sample.csv"}    # offline, from an export

CSV columns: date, channel, page, sessions, users (optional), conversions

Live mode needs:  pip install google-analytics-data
and GOOGLE_APPLICATION_CREDENTIALS pointing at a service account with Viewer access to the property.
"""
from . import in_range, num, read_csv, register, row, to_date


def build_request_params(property_id, start, end):
    """Pure helper, kept separate so it can be tested without the Google library."""
    return {
        "property": f"properties/{property_id}",
        "dimensions": ["date", "sessionDefaultChannelGroup", "pagePath"],
        "metrics": ["sessions", "totalUsers", "keyEvents"],
        "date_range": (start.isoformat(), end.isoformat()),
    }


def _from_csv(cfg, start, end):
    out = []
    for r in read_csv(cfg["csv"]):
        day = to_date(r["date"])
        if in_range(day, start, end):
            out.append(row(day, cfg.get("name", "ga4"), channel=r.get("channel", ""), page=r.get("page", ""),
                           sessions=num(r.get("sessions")), users=num(r.get("users")),
                           conversions=num(r.get("conversions"))))
    return out


def _from_api(cfg, start, end):
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest
    except ImportError:
        raise SystemExit("GA4 live mode needs:  pip install google-analytics-data")
    p = build_request_params(cfg["property"], start, end)
    response = BetaAnalyticsDataClient().run_report(RunReportRequest(
        property=p["property"],
        dimensions=[Dimension(name=d) for d in p["dimensions"]],
        metrics=[Metric(name=m) for m in p["metrics"]],
        date_ranges=[DateRange(start_date=p["date_range"][0], end_date=p["date_range"][1])],
        limit=100000,
    ))
    out = []
    for r in response.rows:
        d = r.dimension_values[0].value
        out.append(row(to_date(f"{d[:4]}-{d[4:6]}-{d[6:]}"), cfg.get("name", "ga4"),
                       channel=r.dimension_values[1].value, page=r.dimension_values[2].value,
                       sessions=num(r.metric_values[0].value), users=num(r.metric_values[1].value),
                       conversions=num(r.metric_values[2].value)))
    return out


@register("ga4")
def fetch(cfg, start, end):
    return _from_csv(cfg, start, end) if cfg.get("csv") else _from_api(cfg, start, end)
