# Stock Notifier v1

This project monitors product pages and can notify you either locally through iMessage or through a Telegram bot.

## Hosted setup

The GitHub Actions version uses a static watchlist in `/Users/imaadaziz/Desktop/web_scrape/watchlist.json` and stores last-known availability in `/Users/imaadaziz/Desktop/web_scrape/data/stock_state.json`.

The scheduled workflow is `/Users/imaadaziz/Desktop/web_scrape/.github/workflows/hourly-stock-check.yml`.

Required GitHub Actions secrets:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

The hosted check command is:

```bash
python3 monitor.py --config watchlist.json hosted-check
```

## What v1 does

- Watches one or more products defined in a JSON config file
- Tries the Shopify product JSON endpoint first for stable variant availability
- Falls back to simple page HTML detection if the product JSON endpoint is unavailable
- Sends a single iMessage when stock changes from out of stock to in stock
- Saves the last known state locally so it does not spam duplicate alerts
- Can list all Shopify variants for a product page so you can discover the exact sizes and colors to watch
- Can accept `/track` commands over Telegram and save watches in SQLite

## Files

- `/Users/imaadaziz/Desktop/web_scrape/monitor.py`: CLI entrypoint
- `/Users/imaadaziz/Desktop/web_scrape/watchers.example.json`: sample config
- `/Users/imaadaziz/Desktop/web_scrape/stock_notifier/`: app code

## Setup

1. Copy `watchers.example.json` to `watchers.json`
2. Replace `recipient` with your iMessage phone number or Apple ID
3. Adjust the product, size, and color as needed

## Commands

Run one check without sending a message:

```bash
python3 monitor.py --config watchers.json check --dry-run
```

Run one real check:

```bash
python3 monitor.py --config watchers.json check
```

Send yourself a test iMessage:

```bash
python3 monitor.py test-notification --recipient "+15555555555"
```

Run the monitor continuously:

```bash
python3 monitor.py --config watchers.json run
```

List variants for a product page:

```bash
python3 monitor.py list-variants --url "https://veiled.com/products/swim-tunic-cove"
```

List variants as JSON:

```bash
python3 monitor.py list-variants --url "https://veiled.com/products/swim-tunic-cove" --json
```

Run the Telegram bot:

```bash
export TELEGRAM_BOT_TOKEN="your-bot-token"
python3 monitor.py telegram-run
```

Send a Telegram test message:

```bash
export TELEGRAM_BOT_TOKEN="your-bot-token"
python3 monitor.py telegram-send-test --chat-id 123456789
```

Run a Telegram auth check:

```bash
python3 monitor.py telegram-self-check
```

## Telegram bot commands

Use these from your Telegram chat with the bot:

```text
/start
/help
/track <url> | <color> | <size>
/list
/remove <id>
/check
/check <id>
/variants <url>
```

Examples:

```text
/track https://veiled.com/products/swim-tunic-cove | Cove | XS
/track https://veiled.com/products/rouched-swim-tunic-black | Black | XXL
```

The bot validates the product immediately, stores the watch in `watchers.db`, and later sends restock alerts back to the same Telegram chat.

## macOS permissions

The first time you send an iMessage through AppleScript, macOS may ask you to allow Terminal or your Python process to control Messages. Approve that prompt or delivery will fail.

## How stock matching works

For Shopify-backed stores, the monitor requests:

```text
https://<store>/products/<handle>.js
```

Then it looks for a variant matching the requested size and color.

- If the store exposes both `Size` and `Color` as variant options, it matches both directly.
- If the page is already color-specific and only `Size` varies, it confirms the page color and then matches the size variant.

For the Veiled page we started with, color appears to be page-level and size is the variant.

## Security note

Do not hardcode your Telegram bot token in the repo. Store it in `TELEGRAM_BOT_TOKEN` locally and later in GitHub Actions Secrets for hosting.

## Hosted next step

You said you do not want to keep your Mac running all the time. The clean hosted version should split into two parts:

1. Hosted checker
   Runs on a small server, cron job, or serverless function and detects stock changes.
2. Notification bridge
   Sends the alert through a provider that works from the cloud.

### Recommended hosted architecture

- Keep the stock checker logic in Python
- Replace the local iMessage sender with a hosted notification provider or use the Telegram bot directly
- Good hosted notification choices:
  - Twilio SMS
  - Email
- Telegram bot
  - Pushover
  - Slack DM

### Important iMessage constraint

True iMessage delivery is not a good fit for pure cloud hosting because Apple does not provide a normal server-side iMessage API for personal automation. In practice, that means:

- Local Mac: true iMessage is straightforward with AppleScript
- Hosted service: use SMS or another push channel instead

### Best practical hosted plan

I recommend this migration path:

1. Use this local v1 to validate stock detection logic on Veiled
2. Run the Telegram-commanded version locally and confirm the command flow you like
3. Deploy the Telegram worker on a hosted platform
4. Keep Telegram as the default hosted alert channel

### Good hosting options

- GitHub Actions on a schedule for low-cost polling
- Railway or Render for a simple always-on worker
- AWS Lambda or Google Cloud Run for serverless polling

If we host it next, I’d recommend Railway, Render, or a small VPS for the Telegram worker because it wants a long-running polling process.
