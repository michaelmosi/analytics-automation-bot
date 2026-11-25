#!/usr/bin/env python3
"""Analytics automation bot: GA4 + Search Console + PostHog + any other marketing channel in one report.

Each data source is a connector (see connectors/). The bot pulls them all into one normalised table,
compares the last 7 days with the 7 days before, cross-checks the sources against each other and
writes a plain-language weekly report with alerts.

    python analytics_bot.py report --config config.sample.json --md weekly_report.md
    python analytics_bot.py report --config config.json --end 2026-11-22 --slack-webhook https://hooks.slack.com/...
    python analytics_bot.py fetch  --config config.json --out combined.csv
    python analytics_bot.py connectors
"""
import argparse
import csv
import json
import urllib.request
from collections import defaultdict
from datetime import date, timedelta

import connectors

DROP_ALERT = -0.20      # flag a fall of 20% or more
SPIKE_ALERT = 0.50      # flag a rise of 50% or more
COST_ALERT = 0.30       # flag cost per conversion rising 30% or more
MISMATCH_ALERT = 0.25   # flag two sources disagreeing on conversions by 25% or more
MIN_VOLUME = 50         # ignore alerts on tiny numbers
ADDITIVE = ("sessions", "users", "pageviews", "conversions", "clicks", "impressions", "spend")


# ------------------------------------------------------------------ data
def load_config(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def gather(config, end):
    """Fetch every configured source for the 14 days ending on `end`."""
    registry = connectors.load_all()
    start = end - timedelta(days=13)
    rows, kinds = [], {}
    for cfg in config["sources"]:
        kind = cfg["type"]
        if kind not in registry:
            raise SystemExit(f"Unknown connector '{kind}'. Available: {', '.join(sorted(registry))}")
        name = cfg.get("name", kind)
        kinds[name] = kind
        rows += registry[kind]({**cfg, "name": name}, start, end)
    return rows, kinds


def split(rows, end):
    cur_start = end - timedelta(days=6)
    prev_start, prev_end = cur_start - timedelta(days=7), cur_start - timedelta(days=1)
    cur = [r for r in rows if cur_start <= r["date"] <= end]
    prev = [r for r in rows if prev_start <= r["date"] <= prev_end]
    return cur, prev, (cur_start, end), (prev_start, prev_end)


def totals(rows):
    t = {m: sum(r.get(m, 0) or 0 for r in rows) for m in ADDITIVE}
    imp = sum(r.get("impressions", 0) or 0 for r in rows if r.get("position"))
    t["position"] = (sum((r["position"] or 0) * (r.get("impressions", 0) or 0) for r in rows if r.get("position")) / imp) if imp else 0.0
    t["ctr"] = (t["clicks"] / t["impressions"]) if t["impressions"] else 0.0
    t["cvr"] = (t["conversions"] / t["sessions"]) if t["sessions"] else 0.0
    t["cpa"] = (t["spend"] / t["conversions"]) if t["conversions"] and t["spend"] else 0.0
    return t


def by_source(rows):
    out = defaultdict(list)
    for r in rows:
        out[r["source"]].append(r)
    return out


def change(new, old):
    return None if not old else (new - old) / old


def fmt_pct(v):
    return "n/a" if v is None else f"{v * 100:+.1f}%"


def _alert(label, metric, new, old, out):
    ch = change(new, old)
    if ch is None or max(new, old) < MIN_VOLUME:
        return
    if ch <= DROP_ALERT:
        out.append(f"DROP: {label} {metric} down {abs(ch) * 100:.0f}% ({old:,.0f} to {new:,.0f})")
    elif ch >= SPIKE_ALERT:
        out.append(f"SPIKE: {label} {metric} up {ch * 100:.0f}% ({old:,.0f} to {new:,.0f})")


# ------------------------------------------------------------------ report
def table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    return lines + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]


def build_report(rows, kinds, end):
    cur, prev, cur_range, prev_range = split(rows, end)
    cur_s, prev_s = by_source(cur), by_source(prev)
    alerts = []
    lines = ["# Weekly marketing analytics report",
             f"{cur_range[0]} to {cur_range[1]} compared with {prev_range[0]} to {prev_range[1]}", ""]

    # 1. headline numbers per source
    head = []
    for name, kind in kinds.items():
        n, p = totals(cur_s.get(name, [])), totals(prev_s.get(name, []))
        if kind == "ga4":
            metrics = [("Sessions", "sessions", "n"), ("Conversions", "conversions", "n"), ("Conversion rate", "cvr", "r")]
        elif kind == "gsc":
            metrics = [("Clicks", "clicks", "n"), ("Impressions", "impressions", "n"), ("CTR", "ctr", "r"), ("Avg position", "position", "p")]
        elif kind == "posthog":
            metrics = [("Users", "users", "n"), ("Pageviews", "pageviews", "n"), ("Conversions", "conversions", "n")]
        else:
            metrics = [("Spend", "spend", "c"), ("Clicks", "clicks", "n"), ("Conversions", "conversions", "n"), ("Cost per conversion", "cpa", "c")]
        for label, key, how in metrics:
            if how == "n":
                head.append((name, label, f"{n[key]:,.0f}", f"{p[key]:,.0f}", fmt_pct(change(n[key], p[key]))))
                _alert(name, label.lower(), n[key], p[key], alerts)
            elif how == "c":
                head.append((name, label, f"{n[key]:,.2f}", f"{p[key]:,.2f}", fmt_pct(change(n[key], p[key]))))
                if key == "cpa" and p[key] and n[key] / p[key] - 1 >= COST_ALERT:
                    alerts.append(f"COST: {name} cost per conversion up {(n[key] / p[key] - 1) * 100:.0f}% ({p[key]:,.2f} to {n[key]:,.2f})")
                if key == "spend":
                    _alert(name, "spend", n[key], p[key], alerts)
            elif how == "r":
                head.append((name, label, f"{n[key] * 100:.2f}%", f"{p[key] * 100:.2f}%", f"{(n[key] - p[key]) * 100:+.2f} pts"))
            else:  # position: lower is better
                head.append((name, label, f"{n[key]:.1f}", f"{p[key]:.1f}", f"{n[key] - p[key]:+.1f}"))
                if p[key] and n[key] - p[key] >= 2:
                    alerts.append(f"RANKING: {name} average position slipped from {p[key]:.1f} to {n[key]:.1f}")
    lines += ["## Headline numbers", ""] + table(["Source", "Metric", "This week", "Last week", "Change"], head) + [""]

    # 2. website channels (GA4)
    for name, kind in kinds.items():
        if kind != "ga4":
            continue
        groups = defaultdict(list)
        for r in cur_s.get(name, []):
            groups[r["channel"] or "(none)"].append(r)
        old = defaultdict(list)
        for r in prev_s.get(name, []):
            old[r["channel"] or "(none)"].append(r)
        body = []
        for ch, rs in sorted(groups.items(), key=lambda kv: totals(kv[1])["conversions"], reverse=True)[:6]:
            t, o = totals(rs), totals(old.get(ch, []))
            body.append((ch, f"{t['sessions']:,.0f}", f"{t['conversions']:,.0f}", f"{t['cvr'] * 100:.2f}%", fmt_pct(change(t["conversions"], o["conversions"]))))
            _alert(f"{name} channel '{ch}'", "sessions", t["sessions"], o["sessions"], alerts)
        lines += [f"## {name}: channels by conversions", ""] + table(["Channel", "Sessions", "Conversions", "Conv. rate", "Conv. change"], body) + [""]

    # 3. search (GSC): top queries and striking distance
    for name, kind in kinds.items():
        if kind != "gsc":
            continue
        q_now, q_old = defaultdict(list), defaultdict(list)
        for r in cur_s.get(name, []):
            q_now[r["query"]].append(r)
        for r in prev_s.get(name, []):
            q_old[r["query"]].append(r)
        top = sorted(q_now.items(), key=lambda kv: totals(kv[1])["clicks"], reverse=True)[:5]
        body = []
        for q, rs in top:
            t, o = totals(rs), totals(q_old.get(q, []))
            body.append((q, f"{t['clicks']:,.0f}", f"{t['impressions']:,.0f}", f"{t['position']:.1f}", fmt_pct(change(t["clicks"], o["clicks"]))))
        for q, rs in q_now.items():
            t, o = totals(rs), totals(q_old.get(q, []))
            if o["position"] and t["impressions"] >= MIN_VOLUME and t["position"] - o["position"] >= 2:
                alerts.append(f"RANKING: '{q}' slipped from position {o['position']:.1f} to {t['position']:.1f}")
        lines += [f"## {name}: top queries", ""] + table(["Query", "Clicks", "Impressions", "Avg position", "Click change"], body) + [""]
        near = [(q, totals(rs)) for q, rs in q_now.items() if 4 <= totals(rs)["position"] <= 15 and totals(rs)["impressions"] >= MIN_VOLUME]
        near.sort(key=lambda x: x[1]["impressions"], reverse=True)
        if near:
            lines += [f"**Striking distance** (ranking 4 to 15, worth a content or title push): " +
                      "; ".join(f"{q} (pos {t['position']:.1f}, {t['impressions']:,.0f} impressions)" for q, t in near[:5]), ""]

    # 4. other channels
    others = [n for n, k in kinds.items() if k not in ("ga4", "gsc", "posthog")]
    if others:
        body = []
        for name in others:
            n, p = totals(cur_s.get(name, [])), totals(prev_s.get(name, []))
            body.append((name, f"{n['spend']:,.2f}", f"{n['clicks']:,.0f}", f"{n['conversions']:,.0f}",
                         f"{n['cpa']:,.2f}" if n["cpa"] else "n/a", fmt_pct(change(n["conversions"], p["conversions"]))))
        lines += ["## Other channels", ""] + table(["Channel", "Spend", "Clicks", "Conversions", "Cost per conversion", "Conv. change"], body) + [""]

    # 5. cross-checks between sources
    checks = []
    ga4 = next((n for n, k in kinds.items() if k == "ga4"), None)
    ph = next((n for n, k in kinds.items() if k == "posthog"), None)
    gsc = next((n for n, k in kinds.items() if k == "gsc"), None)
    if ga4 and ph:
        a, b = totals(cur_s.get(ga4, []))["conversions"], totals(cur_s.get(ph, []))["conversions"]
        if max(a, b) >= MIN_VOLUME and abs(a - b) / max(a, b) >= MISMATCH_ALERT:
            checks.append(f"MISMATCH: {ga4} counts {a:,.0f} conversions but {ph} counts {b:,.0f}. Check that both track the same event and that consent or ad blockers are not hiding one of them.")
    if ga4 and gsc:
        organic = sum(r["sessions"] for r in cur_s.get(ga4, []) if r["channel"].lower() == "organic search")
        clicks = totals(cur_s.get(gsc, []))["clicks"]
        if clicks >= MIN_VOLUME and organic < 0.5 * clicks:
            checks.append(f"GAP: {gsc} reports {clicks:,.0f} clicks but {ga4} only {organic:,.0f} organic sessions. Look at tagging and the cookie banner.")
    alerts += checks
    lines += ["## Cross-checks", ""] + ([f"- {c}" for c in checks] or ["- Sources agree within the thresholds."]) + [""]

    lines += ["## Alerts", ""] + ([f"- {a}" for a in alerts] or ["- No drops, spikes or cost jumps beyond the thresholds."])
    lines += ["", f"_Thresholds: drop {DROP_ALERT * 100:.0f}%, spike +{SPIKE_ALERT * 100:.0f}%, cost +{COST_ALERT * 100:.0f}%, "
                  f"source mismatch {MISMATCH_ALERT * 100:.0f}%, minimum {MIN_VOLUME} events._"]
    return "\n".join(lines) + "\n", alerts


# ------------------------------------------------------------------ cli
def post_slack(webhook, text):
    data = json.dumps({"text": text}).encode()
    req = urllib.request.Request(webhook, data=data, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=15).read()


def resolve_end(args, config):
    raw = args.end or config.get("end")
    return connectors.to_date(raw) if raw else date.today() - timedelta(days=1)


def cmd_report(args):
    config = load_config(args.config)
    end = resolve_end(args, config)
    rows, kinds = gather(config, end)
    text, alerts = build_report(rows, kinds, end)
    if args.md:
        open(args.md, "w", encoding="utf-8").write(text)
        print("wrote", args.md)
    else:
        print(text)
    if args.slack_webhook:
        post_slack(args.slack_webhook, text.splitlines()[0] + "\n" + ("\n".join(alerts) or "No alerts this week."))
        print("posted to Slack")
    return text, alerts


def cmd_fetch(args):
    config = load_config(args.config)
    rows, _ = gather(config, resolve_end(args, config))
    cols = ["date", "source", "channel", "page", "query", *connectors.METRICS]
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows to {args.out}")


def cmd_connectors(args):
    for name in sorted(connectors.load_all()):
        print(name)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Combined marketing analytics bot")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report", help="weekly report across all configured sources")
    r.add_argument("--config", required=True); r.add_argument("--end"); r.add_argument("--md"); r.add_argument("--slack-webhook")
    r.set_defaults(func=cmd_report)
    f = sub.add_parser("fetch", help="dump all sources into one normalised CSV")
    f.add_argument("--config", required=True); f.add_argument("--end"); f.add_argument("--out", default="combined.csv")
    f.set_defaults(func=cmd_fetch)
    c = sub.add_parser("connectors", help="list available connectors")
    c.set_defaults(func=cmd_connectors)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    main()
