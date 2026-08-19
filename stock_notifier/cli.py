from __future__ import annotations

import argparse
import json
import os
import time

from .config import AppConfig, WatchConfig, load_config
from .notifier import IMessageNotifier
from .state import StateStore
from .telegram import TelegramBotClient
from .telegram_bot import TelegramBotRunner
from .tracker import ProductTracker


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor products and send iMessage alerts.")
    parser.add_argument("--config", default="watchers.json", help="Path to the watcher config JSON.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check", help="Run one stock check.")
    check_parser.add_argument("--dry-run", action="store_true", help="Print alerts instead of sending them.")

    run_parser = subparsers.add_parser("run", help="Run checks continuously.")
    run_parser.add_argument("--dry-run", action="store_true", help="Print alerts instead of sending them.")

    notify_parser = subparsers.add_parser("test-notification", help="Send a test iMessage.")
    notify_parser.add_argument("--recipient", required=True, help="Phone number or Apple ID in Messages.")
    notify_parser.add_argument(
        "--message",
        default="Stock notifier test from your local monitor.",
        help="Message body to send.",
    )

    variants_parser = subparsers.add_parser("list-variants", help="List variants for a Shopify product page.")
    variants_parser.add_argument("--url", required=True, help="Product page URL.")
    variants_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit raw JSON for scripting instead of a table.",
    )

    telegram_send_parser = subparsers.add_parser("telegram-send-test", help="Send a test Telegram message.")
    telegram_send_parser.add_argument("--chat-id", required=True, type=int, help="Telegram chat id.")
    telegram_send_parser.add_argument(
        "--message",
        default="Stock notifier Telegram test message.",
        help="Message body to send.",
    )

    telegram_run_parser = subparsers.add_parser(
        "telegram-run",
        help="Run the Telegram bot command loop and periodic stock checker.",
    )
    telegram_run_parser.add_argument("--db", default="watchers.db", help="SQLite database path.")
    telegram_run_parser.add_argument(
        "--interval-minutes",
        default=10,
        type=int,
        help="Default interval for new watches created via Telegram.",
    )
    telegram_run_parser.add_argument(
        "--poll-timeout-seconds",
        default=20,
        type=int,
        help="Telegram getUpdates long-poll timeout.",
    )

    telegram_check_parser = subparsers.add_parser(
        "telegram-self-check",
        help="Validate Telegram auth and show basic bot info.",
    )
    telegram_check_parser.add_argument("--poll-timeout-seconds", default=1, type=int)

    args = parser.parse_args()

    if args.command == "test-notification":
        IMessageNotifier().send(args.recipient, args.message)
        print(f"Sent test message to {args.recipient}")
        return 0
    if args.command == "list-variants":
        tracker = ProductTracker()
        variants = tracker.list_variants(args.url)
        if args.json:
            rows = [
                {
                    "product_title": variant.product_title,
                    "product_handle": variant.product_handle,
                    "variant_id": variant.variant_id,
                    "title": variant.title,
                    "available": variant.available,
                    "options": variant.options,
                }
                for variant in variants
            ]
            print(json.dumps(rows, indent=2))
            return 0
        _print_variants_table(variants)
        return 0
    if args.command == "telegram-send-test":
        token = _telegram_token()
        TelegramBotClient(token).send_message(args.chat_id, args.message)
        print(f"Sent Telegram test message to chat {args.chat_id}")
        return 0
    if args.command == "telegram-run":
        token = _telegram_token()
        runner = TelegramBotRunner(
            token=token,
            db_path=args.db,
            default_interval_minutes=args.interval_minutes,
            poll_timeout_seconds=args.poll_timeout_seconds,
        )
        runner.run_forever()
        return 0
    if args.command == "telegram-self-check":
        token = _telegram_token()
        client = TelegramBotClient(token)
        me = client.get_me()
        updates = client.get_updates(timeout=args.poll_timeout_seconds)
        print(
            json.dumps(
                {
                    "id": me.get("id"),
                    "username": me.get("username"),
                    "first_name": me.get("first_name"),
                    "can_join_groups": me.get("can_join_groups"),
                    "can_read_all_group_messages": me.get("can_read_all_group_messages"),
                    "supports_inline_queries": me.get("supports_inline_queries"),
                    "pending_updates_seen_now": len(updates),
                },
                indent=2,
            )
        )
        return 0

    config = load_config(args.config)
    if args.command == "check":
        return run_check(config, dry_run=args.dry_run)
    if args.command == "run":
        return run_loop(config, dry_run=args.dry_run)
    parser.error(f"Unknown command: {args.command}")
    return 2


def run_loop(config: AppConfig, dry_run: bool) -> int:
    interval_seconds = min(watch.check_interval_minutes for watch in config.watchers) * 60
    while True:
        run_check(config, dry_run=dry_run)
        time.sleep(max(interval_seconds, 60))


def run_check(config: AppConfig, dry_run: bool) -> int:
    tracker = ProductTracker()
    notifier = IMessageNotifier()
    store = StateStore(config.state_file)
    state = store.load()
    had_error = False

    for watch in config.watchers:
        try:
            status = tracker.fetch_status(watch)
        except Exception as exc:
            had_error = True
            print(f"[{watch.name}] check failed for {watch.color} / {watch.size}: {exc}")
            continue
        watch_key = _watch_key(watch)
        previous = state.get(watch_key, {})
        now_in_stock = "true" if status.in_stock else "false"
        previous_in_stock = previous.get("in_stock")

        print(
            f"[{watch.name}] {watch.color} / {watch.size}: "
            f"{'IN STOCK' if status.in_stock else 'out of stock'} via {status.source}"
        )

        if previous_in_stock != now_in_stock and status.in_stock:
            message = (
                f"{watch.name} is back in stock: {watch.color} / {watch.size}. "
                f"Open: {watch.url}"
            )
            if dry_run:
                print(f"DRY RUN alert to {watch.recipient}: {message}")
            else:
                notifier.send(watch.recipient, message)

        state[watch_key] = {
            "in_stock": now_in_stock,
            "url": watch.url,
            "name": watch.name,
            "size": watch.size,
            "color": watch.color,
            "variant_id": status.variant_id or "",
            "variant_label": status.variant_label,
            "product_title": status.product_title,
            "source": status.source,
        }

    store.save(state)
    return 1 if had_error else 0


def _watch_key(watch: WatchConfig) -> str:
    return f"{watch.url}::{watch.color.casefold()}::{watch.size.casefold()}"


def _print_variants_table(variants: list) -> None:
    if not variants:
        print("No variants found.")
        return

    print(f"Product: {variants[0].product_title}")
    print("variant_id        available  options")
    for variant in variants:
        option_bits = [f"{key}={value}" for key, value in variant.options.items()]
        availability = "yes" if variant.available else "no"
        print(f"{variant.variant_id:<16} {availability:<9} {'; '.join(option_bits)}")


def _telegram_token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("Set TELEGRAM_BOT_TOKEN before using Telegram commands.")
    return token
