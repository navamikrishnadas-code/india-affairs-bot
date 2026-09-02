"""
Daily India Current Affairs Telegram Bot
-----------------------------------------
Fetches recent India-related news from free RSS feeds (PIB + major
national dailies), turns each headline into a fact-based Question/Answer
pair using free local NLP (spaCy NER — no paid API needed), and posts a
curated set of 10 to a Telegram channel.

Run manually:  python bot.py
Run on schedule: see .github/workflows/daily-current-affairs.yml
"""

import os
import re
import sys
import html
import requests
import feedparser
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID")  # e.g. @your_channel or -100123456789

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

# ---------------------------------------------------------------------------
# spaCy NER for fact-based Q&A generation (fully free, runs locally)
# ---------------------------------------------------------------------------

import spacy

try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    sys.exit(
        "spaCy model not found. Run:\n"
        "    python -m spacy download en_core_web_sm"
    )

# Entity types we consider "quizzable", in priority order.
PRIORITY_LABELS = ["PERSON", "ORG", "GPE", "MONEY", "PERCENT", "CARDINAL",
                    "EVENT", "NORP", "DATE", "LOC", "FAC"]

QUESTION_PREFIX = {
    "PERSON": "Who is mentioned in the following news",
    "ORG": "Which organisation/company is mentioned in the following news",
    "GPE": "Which country/state is mentioned in the following news",
    "LOC": "Which place is mentioned in the following news",
    "MONEY": "What amount is mentioned in the following news",
    "PERCENT": "What percentage is mentioned in the following news",
    "CARDINAL": "What number is mentioned in the following news",
    "DATE": "What date/period is mentioned in the following news",
    "EVENT": "Which event is mentioned in the following news",
    "NORP": "Which group/nationality is mentioned in the following news",
    "FAC": "Which facility/project is mentioned in the following news",
}


def clean_text(text):
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", "", text)  # strip any stray HTML
    return re.sub(r"\s+", " ", text).strip()


def generate_qa(headline):
    """Blank out the most 'quizzable' entity in a headline to build a
    fact-based Q&A pair. Returns (question, answer) or None if no
    suitable entity is found."""
    doc = nlp(headline)
    candidates = [e for e in doc.ents if e.label_ in PRIORITY_LABELS]
    if not candidates:
        return None

    candidates.sort(key=lambda e: PRIORITY_LABELS.index(e.label_))
    entity = candidates[0]

    blanked = headline[: entity.start_char] + "______" + headline[entity.end_char :]
    prefix = QUESTION_PREFIX.get(entity.label_, "What is referred to in the following news")
    question = f'{prefix}?\n"{blanked}"'
    answer = entity.text
    return question, answer


# ---------------------------------------------------------------------------
# Fetch + curate
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


def build_curated_list(items, n=NUM_ITEMS):
    """Turn raw headlines into Q&A pairs, skipping ones we can't quiz,
    until we have n items (or run out)."""
    curated = []
    for item in items:
        qa = generate_qa(item["title"])
        if not qa:
            continue
        question, answer = qa
        curated.append({"source": item["source"], "question": question, "answer": answer})
        if len(curated) >= n:
            break
    return curated


# ---------------------------------------------------------------------------
# Telegram delivery
# ---------------------------------------------------------------------------

def format_message(curated):
    today = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%d %B %Y")
    lines = [f"🇮🇳 *India Current Affairs — {today}*", ""]
    for i, item in enumerate(curated, 1):
        lines.append(f"*Q{i}.* {escape_md(item['question'])}")
        lines.append(f"➡️ *A:* {escape_md(item['answer'])}  _({escape_md(item['source'])})_")
        lines.append("")
    return "\n".join(lines).strip()


def escape_md(text):
    # Escape Telegram MarkdownV2 special characters.
    for ch in r"_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


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
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    if not resp.ok:
        print(resp.text, file=sys.stderr)
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

    curated = build_curated_list(raw_items, NUM_ITEMS)

    if len(curated) < NUM_ITEMS:
        print(f"[warn] only found {len(curated)} quizzable items (wanted {NUM_ITEMS})",
              file=sys.stderr)

    if not curated:
        print("Could not generate any Q&A pairs today.", file=sys.stderr)
        sys.exit(1)

    message = format_message(curated)
    print(message)  # useful in Actions logs
    send_to_telegram(message)


if __name__ == "__main__":
    main()
