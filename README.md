# India Daily Current Affairs — Telegram Bot

Posts 10 fact-based Q&A current-affairs items to a Telegram channel every
day at 8:00 AM IST. 100% free to run: GitHub Actions for scheduling, RSS
feeds for news, spaCy (local NLP) for Q&A generation — no paid API keys.

## How it works

1. **Fetch** — pulls recent headlines from PIB (official government
   releases) plus The Hindu and Indian Express national feeds.
2. **Curate** — dedupes, keeps items from the last ~30 hours, takes the
   first 10 that can be turned into a Q&A.
3. **Q&A generation** — uses spaCy's named-entity recognition to find the
   most "quizzable" fact in each headline (a person, org, place, amount,
   date, etc.) and blanks it out to form a question, e.g.:
   > Q: Who is mentioned in the following news? "______ launches new
   > semiconductor mission in Assam"
   > A: [Name]
4. **Send** — posts the formatted list to your Telegram channel.

This is a **rule-based** approach (no LLM), so question phrasing is
templated rather than natural language — it's reliable and free, but not
as polished as an AI-written question. If you later get access to a free
tier of an LLM (e.g. Gemini), swap `generate_qa()` for a prompt-based
version for better phrasing.

## One-time setup

### 1. Create the Telegram bot
1. Message [@BotFather](https://t.me/BotFather) on Telegram → `/newbot`
   → follow the prompts.
2. Save the **bot token** it gives you (looks like `123456:ABC-def...`).

### 2. Create the channel and add the bot
1. Create a new Telegram **channel** (public or private).
2. Add your bot as an **administrator** of the channel (needed to post).
3. Get the channel ID:
   - Public channel → use its `@username` directly (e.g. `@my_channel`).
   - Private channel → forward any message from it to
     [@userinfobot](https://t.me/userinfobot) or use the Telegram API's
     `getUpdates` after posting once, to read the numeric ID
     (looks like `-1001234567890`).

### 3. Put the code on GitHub
1. Create a new **public or private** GitHub repo.
2. Push these files (`bot.py`, `requirements.txt`, `README.md`, and the
   `.github/workflows/daily-current-affairs.yml` folder) to it.

### 4. Add your secrets
In the repo: **Settings → Secrets and variables → Actions → New repository secret**
- `TELEGRAM_BOT_TOKEN` → the token from BotFather
- `TELEGRAM_CHANNEL_ID` → your channel's `@username` or numeric ID

### 5. Test it
Go to the **Actions** tab → "Daily India Current Affairs" → **Run workflow**
(this uses the `workflow_dispatch` trigger, so you don't have to wait
until 8 AM to test). Check your channel for the post, and check the
Action's logs if something goes wrong.

That's it — from then on it runs automatically every day at 8:00 AM IST,
for free, on GitHub's infrastructure.

## Running locally (optional, for testing)

```bash
pip install -r requirements.txt
python -m spacy download en_core_web_sm

export TELEGRAM_BOT_TOKEN="your-token"
export TELEGRAM_CHANNEL_ID="@your_channel"

python bot.py
```

## Tuning

- **Change sources** — edit the `RSS_FEEDS` list in `bot.py`. Any RSS
  feed works; e.g. you could add PIB's Hindi feed, or specific ministry
  feeds.
- **Change the time** — edit the `cron` line in the workflow file.
  GitHub Actions cron is in UTC, so IST = UTC + 5:30.
- **Change item count** — edit `NUM_ITEMS` in `bot.py`.
- **Lookback window** — `LOOKBACK_HOURS` controls how far back "today's
  news" reaches; widen it if some days come up short.
