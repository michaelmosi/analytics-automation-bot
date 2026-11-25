"""Connector registry.

A connector is a function ``fetch(cfg, start, end) -> list[dict]`` that returns normalised rows.
Register one with the ``@register("name")`` decorator. Any ``*.py`` file you drop into this folder
is imported automatically, so adding a new marketing channel never means editing the core bot.

Normalised row (every key except ``date`` and ``source`` is optional):

    {
      "date": datetime.date, "source": "ga4",        # which connector / config name produced it
      "channel": "Organic Search", "page": "/blog", "query": "money market fund",
      "sessions": 0, "users": 0, "conversions": 0,   # website and product analytics
      "clicks": 0, "impressions": 0, "position": 0,  # search and ads
      "spend": 0,                                    # paid channels, in your reporting currency
    }
"""
import csv
import importlib
import pkgutil
from datetime import datetime

REGISTRY = {}

METRICS = ("sessions", "users", "pageviews", "conversions", "clicks", "impressions", "spend", "position")


def register(kind):
    def deco(fn):
        REGISTRY[kind] = fn
        return fn
    return deco


def load_all():
    """Import every module in this package so their @register decorators run."""
    for mod in pkgutil.iter_modules(__path__):
        importlib.import_module(f"{__name__}.{mod.name}")
    return REGISTRY


def to_date(value):
    return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()


def num(value):
    try:
        return float(str(value).replace(",", "").replace("%", "").strip() or 0)
    except ValueError:
        return 0.0


def row(day, source, **fields):
    out = {"date": day, "source": source, "channel": "", "page": "", "query": ""}
    out.update(fields)
    return out


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            yield {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}


def in_range(day, start, end):
    return (start is None or day >= start) and (end is None or day <= end)
