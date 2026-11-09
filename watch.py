#!/usr/bin/env python3
"""Feed watcher: checks RSS feeds, and when new matching headlines appear,
fires a Claude scheduled task through its API trigger with the headlines as context.

Config comes from repository secrets (nothing personal lives in this public repo):
  WATCH_FEEDS     JSON list of RSS URLs
  WATCH_KEYWORDS  JSON list of keywords (case-insensitive; empty list = every new item matches)
  FIRE_URL        the scheduled task's Fire URL
  FIRE_TOKEN      the scheduled task's API token
"""
import hashlib
import json
import os
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

STATE_FILE = "state/seen.json"
THROTTLE_SECONDS = 20 * 60      # at most one fire every 20 minutes
MAX_AGE_SECONDS = 3 * 3600      # ignore items older than 3 hours
KEEP_SECONDS = 3 * 86400        # remember seen items for 3 days
MAX_HEADLINES = 10


def load_state():
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    data.setdefault("seen", {})
    data.setdefault("last_fire", 0)
    data.setdefault("pending", [])
    return data


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "news-watch/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def parse_items(xml_bytes):
    root = ET.fromstring(xml_bytes)
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = item.findtext("pubDate")
        try:
            ts = parsedate_to_datetime(pub).timestamp() if pub else time.time()
        except (TypeError, ValueError):
            ts = time.time()
        if title:
            yield {"title": title, "link": link, "ts": ts}


def main():
    feeds = json.loads(os.environ.get("WATCH_FEEDS", "[]"))
    keywords = [k.lower() for k in json.loads(os.environ.get("WATCH_KEYWORDS", "[]"))]
    fire_url = os.environ.get("FIRE_URL", "")
    fire_token = os.environ.get("FIRE_TOKEN", "")
    now = time.time()

    state = load_state()
    first_run = not state["seen"]
    new_matches = []

    for url in feeds:
        try:
            items = list(parse_items(fetch(url)))
        except Exception as e:  # one bad feed must not stop the others
            print(f"feed error: {e}", file=sys.stderr)
            continue
        for it in items:
            key = hashlib.sha1((it["title"] + it["link"]).encode()).hexdigest()[:16]
            if key in state["seen"]:
                continue
            state["seen"][key] = now
            if first_run or now - it["ts"] > MAX_AGE_SECONDS:
                continue  # first run only learns the backlog; old items are ignored
            text = it["title"].lower()
            if not keywords or any(k in text for k in keywords):
                new_matches.append(it)

    # prune memory
    state["seen"] = {k: v for k, v in state["seen"].items() if now - v < KEEP_SECONDS}

    # queue matches; fire only when the throttle allows
    state["pending"].extend(new_matches)
    state["pending"] = [p for p in state["pending"] if now - p["ts"] < MAX_AGE_SECONDS]
    fired = False
    if state["pending"] and now - state["last_fire"] >= THROTTLE_SECONDS:
        if not (fire_url and fire_token):
            print("FIRE_URL / FIRE_TOKEN not set; skipping fire", file=sys.stderr)
        else:
            batch = sorted(state["pending"], key=lambda p: -p["ts"])[:MAX_HEADLINES]
            lines = [
                f"- {time.strftime('%Y-%m-%d %H:%M', time.gmtime(p['ts']))} UTC | {p['title']} | {p['link']}"
                for p in batch
            ]
            body = json.dumps({"text": "WATCHER HEADLINES (unverified leads):\n" + "\n".join(lines)}).encode()
            req = urllib.request.Request(
                fire_url,
                data=body,
                method="POST",
                headers={
                    "Authorization": f"Bearer {fire_token}",
                    "anthropic-beta": "experimental-cc-routine-2026-04-01",
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    print(f"fired: HTTP {r.status}, {len(batch)} headlines")
                state["last_fire"] = now
                state["pending"] = []
                fired = True
            except Exception as e:
                print(f"fire failed (will retry next run): {e}", file=sys.stderr)

    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=0, sort_keys=True)
    print(f"feeds={len(feeds)} new_matches={len(new_matches)} pending={len(state['pending'])} fired={fired}")


if __name__ == "__main__":
    main()
