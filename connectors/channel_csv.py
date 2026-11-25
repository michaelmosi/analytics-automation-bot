"""Generic channel connector: the slot for every other marketing channel.

Meta Ads, TikTok, LinkedIn, email (Zoho, Mailchimp), influencers, PR: if it can be exported as a CSV,
it plugs in here with no code. Add one entry per channel to the config:

    {"type": "channel_csv", "name": "meta_ads", "csv": "exports/meta.csv",
     "columns": {"date": "Day", "spend": "Amount spent (USD)", "impressions": "Impressions",
                 "clicks": "Link clicks", "conversions": "Results"}}

Any of the standard column names can be remapped to whatever the platform calls them. Missing columns
are treated as zero. For anything that needs an API, write a new connector instead: copy this file,
call fetch() against that API, and decorate it with @register("your_channel").
"""
from . import in_range, num, read_csv, register, row, to_date

STANDARD = ("date", "channel", "page", "spend", "impressions", "clicks", "conversions", "sessions")


@register("channel_csv")
def fetch(cfg, start, end):
    cols = {k: (cfg.get("columns", {}).get(k, k)).strip().lower() for k in STANDARD}
    name = cfg.get("name", "channel")
    out = []
    for r in read_csv(cfg["csv"]):
        if not r.get(cols["date"]):
            continue
        day = to_date(r[cols["date"]])
        if not in_range(day, start, end):
            continue
        out.append(row(day, name, channel=r.get(cols["channel"], "") or cfg.get("channel", name),
                       page=r.get(cols["page"], ""), spend=num(r.get(cols["spend"])),
                       impressions=num(r.get(cols["impressions"])), clicks=num(r.get(cols["clicks"])),
                       conversions=num(r.get(cols["conversions"])), sessions=num(r.get(cols["sessions"]))))
    return out
