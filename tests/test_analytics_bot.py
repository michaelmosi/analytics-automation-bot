import json
import os
import sys
import tempfile
import textwrap
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # sample configs use relative paths

import analytics_bot as bot  # noqa: E402
import connectors  # noqa: E402
from connectors import ga4, gsc, posthog  # noqa: E402

END = date(2026, 11, 15)


def run_report():
    config = bot.load_config("config.sample.json")
    rows, kinds = bot.gather(config, END)
    return bot.build_report(rows, kinds, END), rows, kinds


class ConnectorTests(unittest.TestCase):
    def test_registry_has_builtin_connectors(self):
        self.assertTrue({"ga4", "gsc", "posthog", "channel_csv"} <= set(connectors.load_all()))

    def test_every_source_returns_normalised_rows(self):
        _, rows, kinds = run_report()
        self.assertEqual(set(kinds), {"ga4", "search_console", "posthog", "meta_ads", "email_zoho"})
        for r in rows:
            self.assertIn("date", r)
            self.assertIn("source", r)
            self.assertIsInstance(r["date"], date)

    def test_channel_csv_maps_platform_column_names(self):
        rows = connectors.load_all()["channel_csv"](
            {"name": "meta_ads", "csv": "samples/meta_ads.sample.csv",
             "columns": {"date": "Day", "spend": "Amount spent (USD)", "clicks": "Link clicks", "conversions": "Results"}},
            None, None)
        self.assertEqual(len(rows), 14)
        self.assertEqual(rows[0]["spend"], 40.0)
        self.assertGreater(rows[0]["conversions"], 0)

    def test_new_channel_can_be_added_without_touching_the_core(self):
        @connectors.register("fake_tiktok")
        def fetch(cfg, start, end):
            return [connectors.row(date(2026, 11, 10), cfg["name"], clicks=100.0, conversions=7.0, spend=30.0)]
        rows, kinds = bot.gather({"sources": [{"type": "fake_tiktok", "name": "tiktok"}]}, END)
        self.assertEqual(kinds, {"tiktok": "fake_tiktok"})
        self.assertEqual(rows[0]["source"], "tiktok")
        connectors.REGISTRY.pop("fake_tiktok")

    def test_unknown_connector_is_a_clear_error(self):
        with self.assertRaises(SystemExit) as ctx:
            bot.gather({"sources": [{"type": "nope"}]}, END)
        self.assertIn("Unknown connector", str(ctx.exception))


class ApiRequestTests(unittest.TestCase):
    def test_ga4_request_params(self):
        p = ga4.build_request_params("123", date(2026, 11, 2), date(2026, 11, 15))
        self.assertEqual(p["property"], "properties/123")
        self.assertEqual(p["date_range"], ("2026-11-02", "2026-11-15"))
        self.assertIn("sessionDefaultChannelGroup", p["dimensions"])

    def test_gsc_request_body(self):
        b = gsc.build_request_body(date(2026, 11, 2), date(2026, 11, 15), start_row=25000)
        self.assertEqual(b["dimensions"], ["date", "query", "page"])
        self.assertEqual(b["startRow"], 25000)

    def test_posthog_query_validates_event_name(self):
        q = posthog.build_hogql("sign_up", date(2026, 11, 2), date(2026, 11, 15))
        self.assertIn("countIf(event = 'sign_up')", q)
        with self.assertRaises(ValueError):
            posthog.build_hogql("x'); DROP TABLE events; --", date(2026, 11, 2), date(2026, 11, 15))

    def test_posthog_live_mode_posts_hogql_with_bearer_key(self):
        fake = mock.MagicMock()
        fake.__enter__.return_value.read.return_value = json.dumps({"results": [["2026-11-10", 50, 200, 4]]}).encode()
        with mock.patch.dict(os.environ, {"POSTHOG_PERSONAL_API_KEY": "phx_test"}), \
                mock.patch("connectors.posthog.urllib.request.urlopen", return_value=fake) as urlopen:
            rows = posthog.fetch({"name": "posthog", "project_id": "99", "host": "https://eu.posthog.com"},
                                 date(2026, 11, 2), date(2026, 11, 15))
        req = urlopen.call_args[0][0]
        self.assertEqual(req.full_url, "https://eu.posthog.com/api/projects/99/query/")
        self.assertEqual(req.get_header("Authorization"), "Bearer phx_test")
        self.assertEqual(rows[0]["conversions"], 4.0)


class ReportTests(unittest.TestCase):
    def test_report_flags_every_planted_pattern(self):
        (text, alerts), _, _ = run_report()
        joined = " ".join(alerts)
        self.assertIn("ga4 channel 'Social' sessions down", joined)       # DROP
        self.assertIn("email_zoho conversions up", joined)                # SPIKE
        self.assertIn("meta_ads cost per conversion up", joined)          # COST
        self.assertIn("MISMATCH: ga4 counts", joined)                     # cross-source
        self.assertIn("RANKING: 'mmf calculator' slipped", joined)        # search ranking
        self.assertIn("## Cross-checks", text)

    def test_report_has_a_section_per_source_type(self):
        (text, _), _, _ = run_report()
        for heading in ("## Headline numbers", "## ga4: channels by conversions", "## search_console: top queries", "## Other channels"):
            self.assertIn(heading, text)

    def test_quiet_data_produces_no_alerts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "flat.csv"
            lines = ["date,channel,page,sessions,users,conversions"]
            for i in range(14):
                lines.append(f"2026-11-{2 + i:02d},Organic Search,/,300,250,10")
            path.write_text("\n".join(lines))
            rows, kinds = bot.gather({"sources": [{"type": "ga4", "name": "ga4", "csv": str(path)}]}, END)
            _, alerts = bot.build_report(rows, kinds, END)
            self.assertEqual(alerts, [])

    def test_small_numbers_do_not_alert(self):
        out = []
        bot._alert("tiny", "sessions", 10, 40, out)
        self.assertEqual(out, [])

    def test_fetch_command_writes_combined_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "combined.csv"
            bot.main(["fetch", "--config", "config.sample.json", "--out", str(out)])
            lines = out.read_text().splitlines()
            self.assertGreater(len(lines), 100)
            self.assertTrue(lines[0].startswith("date,source,channel"))


if __name__ == "__main__":
    unittest.main()
