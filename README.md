# news-watch

Every 5 minutes, a GitHub Action checks a few news RSS feeds. When a new headline matches the keywords, it fires a Claude scheduled task through its API trigger, passing the headlines along as unverified leads. Claude then verifies them and decides whether to send a push alert.

- `watch.py`: fetches the feeds, de-duplicates items, applies the keyword filter, throttles to at most 1 fire every 20 minutes, and fires the task.
- `state/seen.json`: headlines already seen. The workflow commits it back after each run.
- All configuration lives in repository secrets, not in this repo: `WATCH_FEEDS`, `WATCH_KEYWORDS`, `FIRE_URL` and `FIRE_TOKEN`.

The first run only records the current backlog of headlines and fires nothing.

To pause the watcher, go to Actions → news-watch → "Disable workflow".
