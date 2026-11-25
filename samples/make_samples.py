"""Regenerates the sample exports. Deterministic, so the tests can rely on the planted patterns:

  - Social sessions fall sharply in the second week          (DROP alert)
  - Email conversions spike in the second week               (SPIKE alert)
  - Meta Ads cost per conversion rises                       (COST alert)
  - PostHog counts far fewer conversions than GA4            (MISMATCH cross-check)
  - One search query slips in ranking                        (RANKING alert)
"""
import csv
import datetime
import os

HERE = os.path.dirname(os.path.abspath(__file__))
START = datetime.date(2026, 11, 2)   # 14 days: 2 to 15 November 2026


def write(name, header, rows):
    with open(os.path.join(HERE, name), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


ga4, gsc, ph, meta, email = [], [], [], [], []
for i in range(14):
    d = (START + datetime.timedelta(days=i)).isoformat()
    wk2 = i >= 7
    for ch, page, s, c in (("Organic Search", "/ke/products/money-market-funds", 420, 12),
                           ("Social", "/blog/kibaba-fund", 300, 6),
                           ("Email", "/mmf-calculator", 80, 5)):
        s, c = s + (i % 3) * 10, c + (i % 2)
        if wk2 and ch == "Social":
            s, c = int(s * 0.6), int(c * 0.5)
        if wk2 and ch == "Email":
            s, c = int(s * 1.8), int(c * 2.0)
        ga4.append([d, ch, page, s, int(s * 0.8), c])
    # Search Console: three queries
    for q, page, clicks, imp, pos in (("money market fund kenya", "/ke/products/money-market-funds", 60, 2200, 6.4),
                                      ("mmf calculator", "/mmf-calculator", 45, 600, 3.1),
                                      ("best unit trust kenya", "/blog/kibaba-fund", 20, 900, 8.2)):
        pos2 = pos + (2.6 if wk2 and q == "mmf calculator" else 0)
        gsc.append([d, q, page, clicks + (i % 4), imp + 15 * (i % 3), round(pos2, 1)])
    # PostHog: counts about 60% of GA4 conversions
    ph.append([d, 260 + (i % 5) * 8, 900 + (i % 4) * 25, 14 + (i % 3)])
    # Meta Ads: cost per conversion rises in week two
    spend = 40.0
    meta.append([d, spend, 5200 + (i % 3) * 100, 180 + (i % 4) * 5, (9 if not wk2 else 5) + (i % 2)])
    # Email (Zoho): clicks and conversions rise in week two
    email.append([d, "Email", 0, 0, 120 if not wk2 else 260, (6 if not wk2 else 15)])

write("ga4.sample.csv", ["date", "channel", "page", "sessions", "users", "conversions"], ga4)
write("gsc.sample.csv", ["date", "query", "page", "clicks", "impressions", "position"], gsc)
write("posthog.sample.csv", ["date", "users", "pageviews", "conversions"], ph)
write("meta_ads.sample.csv", ["Day", "Amount spent (USD)", "Impressions", "Link clicks", "Results"], meta)
write("email.sample.csv", ["date", "channel", "spend", "impressions", "clicks", "conversions"], email)
print("samples written")
