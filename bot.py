"""
Daily India Current Affairs Telegram Bot
-----------------------------------------
Fetches recent India-related news from free RSS feeds (PIB + major
national dailies), asks Google Gemini's free tier to pick the 10 most
noteworthy items and turn them into natural, exam-style fact-based Q&A
pairs, and posts the result to a Telegram channel.

Run manually:  python bot.py
Run on schedule: see .github/workflows/daily-current-affairs.yml
"""

import os
import re
import sys
import json
import html
import requests
import feedparser
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID")  # e.g. @your_channel or -100123456789
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# "-latest" alias: Google hot-swaps this to whichever current Flash-Lite
# model is live, so this keeps working even after specific model versions
# get retired — no code changes needed when that happens.
GEMINI_MODEL = "gemini-flash-lite-latest"

NUM_ITEMS = 10

# Free RSS sources. PIB gives official government announcements
# (schemes, policy, appointments) which is exactly what most India
# current-affairs / exam-prep audiences want. The other two add
# general national news for breadth.
RSS_FEEDS = [
    ("PIB", "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=1"),
    ("The Hindu", "https://www.thehindu.com/news/national/feeder/default.rss"),
    ("Indian Express", "https://indianexpress.com/section/india/feed/"),
]

# How far back to look for "today's" news (in hours). RSS publish times
# can be inconsistent, so we use a rolling window rather than a strict
# calendar-day match.
LOOKBACK_HOURS = 30

# How many raw headlines to feed Gemini so it has enough to choose the
# best 10 from (keeps token usage small and free-tier friendly).
MAX_CANDIDATES_FOR_GEMINI = 25


def clean_text(text):
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", "", text)  # strip any stray HTML
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Fetch + dedupe
# ---------------------------------------------------------------------------

def fetch_candidates():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    items = []

    for source_name, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"[warn] failed to fetch {source_name}: {e}", file=sys.stderr)
            continue

        for entry in feed.entries:
            title = clean_text(getattr(entry, "title", ""))
            if not title:
                continue

            published = None
            for field in ("published_parsed", "updated_parsed"):
                val = getattr(entry, field, None)
                if val:
                    published = datetime(*val[:6], tzinfo=timezone.utc)
                    break

            if published and published < cutoff:
                continue  # too old

            items.append({"source": source_name, "title": title, "published": published})

    return items


def dedupe(items):
    seen = set()
    unique = []
    for item in items:
        key = re.sub(r"[^a-z0-9]", "", item["title"].lower())[:60]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


# ---------------------------------------------------------------------------
# Gemini: pick the best headlines and write natural Q&A pairs
# ---------------------------------------------------------------------------

def generate_qa_with_gemini(items):
    if not GEMINI_API_KEY:
        raise RuntimeError("Set the GEMINI_API_KEY environment variable.")

    candidates = items[:MAX_CANDIDATES_FOR_GEMINI]
    headline_list = "\n".join(
        f"{i+1}. [{c['source']}] {c['title']}" for i, c in enumerate(candidates)
    )

    prompt = f"""You are preparing a daily India current-affairs quiz for
competitive exam aspirants (UPSC / SSC / Banking style).

Below are today's India news headlines. Pick the {NUM_ITEMS} most
noteworthy, exam-relevant, and clearly factual ones (prefer government
schemes, appointments, policy, achievements, and important national
events over routine crime/court stories).

For each one, write:
- a natural, well-phrased quiz question (like a real GK quiz, e.g.
  "Which state launched a new solar power scheme this week?" or
  "Who was appointed as the new Chief Justice of India?")
- a short, precise factual answer (a few words)

Base every question strictly on the facts in the headline — do not
invent details. Avoid fill-in-the-blank or "___" style questions;
write them as a person would naturally ask them.

Headlines:
{headline_list}

Respond with ONLY a valid JSON array (no markdown fences, no extra
text), like this:
[{{"question": "...", "answer": "..."}}, ...]
Return exactly {NUM_ITEMS} items if possible."""

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent"
    )
    resp = requests.post(
        url,
        headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=60,
    )
    if not resp.ok:
        print(f"GEMINI ERROR RESPONSE: {resp.text}", file=sys.stderr)
        resp.raise_for_status()

    data = resp.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"].strip()

    # Strip accidental markdown code fences if the model adds them anyway.
    text = re.sub(r"^```(json)?", "", text.strip())
    text = re.sub(r"```$", "", text.strip()).strip()

    pairs = json.loads(text)
    curated = []
    for pair in pairs[:NUM_ITEMS]:
        q = clean_text(pair.get("question", ""))
        a = clean_text(pair.get("answer", ""))
        if q and a:
            curated.append({"question": q, "answer": a})
    return curated


# ---------------------------------------------------------------------------
# Telegram delivery
# ---------------------------------------------------------------------------

def format_message(curated):
    today = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%d %B %Y")
    lines = [f"🇮🇳 India Current Affairs — {today}", ""]
    for i, item in enumerate(curated, 1):
        lines.append(f"Q{i}. {item['question']}")
        lines.append(f"➡️ A: {item['answer']}")
        lines.append("")
    return "\n".join(lines).strip()


def send_to_telegram(message):
    if not BOT_TOKEN or not CHANNEL_ID:
        raise RuntimeError(
            "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID environment variables."
        )

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        data={
            "chat_id": CHANNEL_ID,
            "text": message,
            # Plain text — no parse_mode — avoids Telegram's strict
            # MarkdownV2 escaping rules rejecting the message.
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    if not resp.ok:
        print(f"TELEGRAM ERROR RESPONSE: {resp.text}", file=sys.stderr)
        resp.raise_for_status()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    raw_items = fetch_candidates()
    raw_items = dedupe(raw_items)

    if not raw_items:
        print("No recent items found from any feed.", file=sys.stderr)
        sys.exit(1)

    curated = generate_qa_with_gemini(raw_items)

    if not curated:
        print("Gemini returned no usable Q&A pairs today.", file=sys.stderr)
        sys.exit(1)

    if len(curated) < NUM_ITEMS:
        print(f"[warn] only got {len(curated)} items (wanted {NUM_ITEMS})", file=sys.stderr)

    message = format_message(curated)
    print(message)  # useful in Actions logs
    send_to_telegram(message)


if __name__ == "__main__":
    main()
