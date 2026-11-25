# Analytics automation bot

One weekly report across **GA4, Google Search Console, PostHog and any other marketing channel**. Each data source is a small connector; the bot pulls them into one table, compares the last 7 days with the 7 days before, cross-checks the sources against each other and writes a plain-language report with alerts.

## What the report contains
- Headline numbers per source with week-over-week change
- GA4 channels by conversions, top Search Console queries and "striking distance" queries (ranking 4 to 15)
- Spend, clicks, conversions and cost per conversion for every other channel
- **Cross-checks:** GA4 against PostHog conversions, and GA4 organic sessions against Search Console clicks, so tracking gaps show up
- **Alerts:** drops of 20%+, spikes of 50%+, cost per conversion up 30%+, ranking slips of 2+ positions, and source mismatches of 25%+ (tiny volumes are ignored)

## Try it with the sample data
```bash
python analytics_bot.py report --config config.sample.json --md weekly_report.md
```

## Connect your real sources
Copy `config.live.example.json` to `config.json`, then:

| Source | Live mode needs |
| --- | --- |
| GA4 | `pip install google-analytics-data`, `GOOGLE_APPLICATION_CREDENTIALS` (service account with Viewer on the property) |
| Search Console | `pip install google-api-python-client google-auth`, a service account added as a user on the property |
| PostHog | `POSTHOG_PERSONAL_API_KEY` (a personal key with query access); standard library only |
| Anything else | export a CSV and map its column names in the config, no code |

Every connector also works from a CSV export (`"csv": "path"`), so you can start without any credentials.

```bash
python analytics_bot.py report --config config.json --md report.md
python analytics_bot.py report --config config.json --slack-webhook https://hooks.slack.com/services/...
python analytics_bot.py fetch  --config config.json --out combined.csv     # one normalised table of all sources
python analytics_bot.py connectors                                         # list what is available
```

## Add another marketing channel
- **From a CSV export** (Meta Ads, TikTok, LinkedIn, Zoho, Mailchimp): add a `channel_csv` entry to the config and map the column names. No code.
- **From an API:** drop a new file in `connectors/`, write `fetch(cfg, start, end)` returning normalised rows, and decorate it with `@register("your_channel")`. It is picked up automatically; the core bot never changes. `connectors/channel_csv.py` is the template.

## Notes and limits
- The GA4, Search Console and PostHog live modes need your credentials, so they are covered by tests with mocked requests, not by calls to the real services.
- Schedule it weekly with cron, Windows Task Scheduler or a GitHub Action.

## Tests
```bash
python -m unittest discover tests
```
