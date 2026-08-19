from __future__ import annotations

import time
from dataclasses import dataclass

from .config import WatchConfig
from .db import WatchRecord, WatchRepository
from .tracker import ProductTracker
from .telegram import TelegramBotClient, TelegramUpdate


HELP_TEXT = """Commands:
/track <url> | <color> | <size>
/track-page <url>
/list
/remove <id>
/remove <id1> <id2>
/remove <id1,id2,id3>
/check
/check <id>
/variants <url>
/help"""


@dataclass
class TelegramBotRunner:
    token: str
    db_path: str
    default_interval_minutes: int = 10
    poll_timeout_seconds: int = 20

    def run_forever(self) -> None:
        client = TelegramBotClient(self.token)
        repo = WatchRepository(path=self._path())
        tracker = ProductTracker()

        while True:
            self._run_due_checks(repo, tracker, client)
            offset = self._get_offset(repo)
            updates = client.get_updates(offset=offset, timeout=self.poll_timeout_seconds)
            for update in updates:
                self._handle_update(update, repo, tracker, client)
                repo.set_setting("telegram_offset", str(update.update_id + 1))

    def _handle_update(
        self,
        update: TelegramUpdate,
        repo: WatchRepository,
        tracker: ProductTracker,
        client: TelegramBotClient,
    ) -> None:
        repo.set_setting(f"last_chat_id:{update.chat_id}", str(update.chat_id))
        text = update.text.strip()
        if text.startswith("/start"):
            client.send_message(update.chat_id, "Stock notifier is ready.\n\n" + HELP_TEXT)
            return
        if text.startswith("/help"):
            client.send_message(update.chat_id, HELP_TEXT)
            return
        if text.startswith("/list"):
            watches = repo.list_watches(update.chat_id)
            if not watches:
                client.send_message(update.chat_id, "No watches yet. Use /track <url> | <color> | <size>.")
                return
            lines = ["Your watches:"]
            for watch in watches:
                status = self._human_status(watch.last_in_stock)
                lines.append(
                    f"#{watch.id} | {watch.name} | size {watch.size} | color {watch.color} | last status: {status}"
                )
            client.send_message(update.chat_id, "\n".join(lines))
            return
        if text.startswith("/remove"):
            self._handle_remove(text, update.chat_id, repo, client)
            return
        if text.startswith("/check"):
            self._handle_check(text, update.chat_id, repo, tracker, client)
            return
        if text.startswith("/variants"):
            self._handle_variants(text, update.chat_id, tracker, client)
            return
        if text.startswith("/track-page"):
            self._handle_track_page(text, update.chat_id, repo, tracker, client)
            return
        if text.startswith("/track"):
            self._handle_track(text, update.chat_id, repo, tracker, client)
            return
        client.send_message(update.chat_id, "I didn't understand that command.\n\n" + HELP_TEXT)

    def _handle_track(
        self,
        text: str,
        chat_id: int,
        repo: WatchRepository,
        tracker: ProductTracker,
        client: TelegramBotClient,
    ) -> None:
        payload = text[len("/track") :].strip()
        parts = [part.strip() for part in payload.split("|")]
        if len(parts) != 3 or not all(parts):
            client.send_message(
                chat_id,
                "Use: /track <url> | <color> | <size>\n"
                "Example: /track https://veiled.com/products/swim-tunic-cove | Cove | XS",
            )
            return

        url, color, size = parts
        watch = WatchConfig(
            name=f"{color} {size}",
            url=url,
            size=size,
            color=color,
            recipient=str(chat_id),
            check_interval_minutes=self.default_interval_minutes,
        )
        try:
            status = tracker.fetch_status(watch)
        except Exception as exc:
            client.send_message(chat_id, f"Couldn't validate that watch: {exc}")
            return

        try:
            watch_id = repo.add_watch(
                chat_id=chat_id,
                name=status.product_title,
                url=url,
                color=color,
                size=size,
                interval_minutes=self.default_interval_minutes,
                variant_id=status.variant_id or "",
                variant_label=status.variant_label,
                last_in_stock="true" if status.in_stock else "false",
            )
        except ValueError as exc:
            if str(exc) != "duplicate_watch":
                client.send_message(chat_id, f"Couldn't save that watch: {exc}")
                return
            client.send_message(chat_id, "That watch already exists for this chat.")
            return

        client.send_message(
            chat_id,
            "\n".join(
                [
                    f"Tracking #{watch_id}",
                    status.product_title,
                    f"Color: {color}",
                    f"Size: {size}",
                    f"Status right now: {'in stock' if status.in_stock else 'out of stock'}",
                    f"Variant: {status.variant_label}",
                ]
            ),
        )

    def _handle_track_page(
        self,
        text: str,
        chat_id: int,
        repo: WatchRepository,
        tracker: ProductTracker,
        client: TelegramBotClient,
    ) -> None:
        url = text[len("/track-page") :].strip()
        if not url:
            client.send_message(chat_id, "Use: /track-page <url>")
            return

        try:
            variants = tracker.list_variants(url)
        except Exception as exc:
            client.send_message(chat_id, f"Couldn't load variants from that page: {exc}")
            return

        created = 0
        skipped = 0
        product_title = variants[0].product_title if variants else url
        inferred_color = self._infer_color_from_variants(variants, url)

        for variant in variants:
            size = self._extract_size(variant.options, variant.title)
            color = self._extract_color(variant.options, inferred_color)
            watch = WatchConfig(
                name=product_title,
                url=url,
                size=size,
                color=color,
                recipient=str(chat_id),
                check_interval_minutes=self.default_interval_minutes,
            )
            try:
                status = tracker.fetch_status(watch)
                repo.add_watch(
                    chat_id=chat_id,
                    name=status.product_title,
                    url=url,
                    color=color,
                    size=size,
                    interval_minutes=self.default_interval_minutes,
                    variant_id=status.variant_id or variant.variant_id,
                    variant_label=status.variant_label,
                    last_in_stock="true" if status.in_stock else "false",
                )
                created += 1
            except ValueError as exc:
                if str(exc) == "duplicate_watch":
                    skipped += 1
                    continue
                client.send_message(chat_id, f"Stopped while adding page watches: {exc}")
                return
            except Exception as exc:
                client.send_message(chat_id, f"Stopped while validating variants: {exc}")
                return

        client.send_message(
            chat_id,
            "\n".join(
                [
                    f"Processed page watches for {product_title}",
                    f"Created: {created}",
                    f"Skipped existing: {skipped}",
                    f"Color used: {inferred_color}",
                ]
            ),
        )

    def _handle_remove(
        self,
        text: str,
        chat_id: int,
        repo: WatchRepository,
        client: TelegramBotClient,
    ) -> None:
        payload = text[len("/remove") :].strip()
        ids = self._parse_remove_ids(payload)
        if not ids:
            client.send_message(chat_id, "Use: /remove <id> or /remove <id1,id2,id3>")
            return
        removed_ids: list[int] = []
        missing_ids: list[int] = []
        for watch_id in ids:
            removed = repo.remove_watch(chat_id, watch_id)
            if removed:
                removed_ids.append(watch_id)
            else:
                missing_ids.append(watch_id)

        lines: list[str] = []
        if removed_ids:
            lines.append("Removed: " + ", ".join(f"#{watch_id}" for watch_id in removed_ids))
        if missing_ids:
            lines.append("Not found: " + ", ".join(f"#{watch_id}" for watch_id in missing_ids))
        client.send_message(chat_id, "\n".join(lines) if lines else "Nothing removed.")

    def _handle_check(
        self,
        text: str,
        chat_id: int,
        repo: WatchRepository,
        tracker: ProductTracker,
        client: TelegramBotClient,
    ) -> None:
        payload = text[len("/check") :].strip()
        if not payload:
            watches = repo.list_watches(chat_id)
            if not watches:
                client.send_message(chat_id, "No watches yet.")
                return
            lines = ["Current status:"]
            for watch in watches:
                lines.append(self._check_watch(watch, repo, tracker, client, send_alert=False))
            client.send_message(chat_id, "\n".join(lines))
            return

        if not payload.isdigit():
            client.send_message(chat_id, "Use: /check or /check <id>")
            return
        watch = repo.get_watch(chat_id, int(payload))
        if watch is None:
            client.send_message(chat_id, "No watch found with that id.")
            return
        line = self._check_watch(watch, repo, tracker, client, send_alert=False)
        client.send_message(chat_id, line)

    def _handle_variants(
        self,
        text: str,
        chat_id: int,
        tracker: ProductTracker,
        client: TelegramBotClient,
    ) -> None:
        payload = text[len("/variants") :].strip()
        if not payload:
            client.send_message(chat_id, "Use: /variants <url>")
            return
        try:
            variants = tracker.list_variants(payload)
        except Exception as exc:
            client.send_message(chat_id, f"Couldn't list variants: {exc}")
            return
        lines = [f"Variants for {variants[0].product_title}:"]
        for variant in variants:
            options = ", ".join(f"{key}={value}" for key, value in variant.options.items())
            lines.append(
                f"{variant.variant_id}: {'in stock' if variant.available else 'out of stock'} | {options}"
            )
        client.send_message(chat_id, "\n".join(lines[:30]))

    def _run_due_checks(
        self,
        repo: WatchRepository,
        tracker: ProductTracker,
        client: TelegramBotClient,
    ) -> None:
        now_ts = int(time.time())
        for watch in repo.due_watches(now_ts):
            self._check_watch(watch, repo, tracker, client, send_alert=True)

    def _check_watch(
        self,
        watch: WatchRecord,
        repo: WatchRepository,
        tracker: ProductTracker,
        client: TelegramBotClient,
        send_alert: bool,
    ) -> str:
        config = WatchConfig(
            name=watch.name,
            url=watch.url,
            size=watch.size,
            color=watch.color,
            recipient=str(watch.chat_id),
            check_interval_minutes=watch.interval_minutes,
        )
        try:
            status = tracker.fetch_status(config)
        except Exception as exc:
            return f"#{watch.id} {watch.name} | {watch.color} / {watch.size} | check failed: {exc}"

        current = "true" if status.in_stock else "false"
        previous = watch.last_in_stock
        now_ts = int(time.time())
        repo.update_watch_status(
            watch_id=watch.id,
            last_in_stock=current,
            checked_at=now_ts,
            variant_id=status.variant_id or "",
            variant_label=status.variant_label,
            name=status.product_title,
        )

        if send_alert and previous != current and status.in_stock:
            client.send_message(
                watch.chat_id,
                "\n".join(
                    [
                        f"Restock alert for #{watch.id}",
                        status.product_title,
                        f"{watch.color} / {watch.size} is back in stock.",
                        watch.url,
                    ]
                ),
            )

        return (
            f"#{watch.id} {status.product_title} | {watch.color} / {watch.size} | "
            f"{'in stock' if status.in_stock else 'out of stock'}"
        )

    def _get_offset(self, repo: WatchRepository) -> int | None:
        value = repo.get_setting("telegram_offset")
        return int(value) if value is not None else None

    def _path(self):
        from pathlib import Path

        return Path(self.db_path)

    def _human_status(self, value: str | None) -> str:
        if value == "true":
            return "in stock"
        if value == "false":
            return "out of stock"
        return "unknown"

    def _parse_remove_ids(self, payload: str) -> list[int]:
        if not payload:
            return []
        normalized = payload.replace(",", " ")
        ids: list[int] = []
        for part in normalized.split():
            if not part.isdigit():
                return []
            ids.append(int(part))
        return ids

    def _extract_size(self, options: dict[str, str], fallback_title: str) -> str:
        for key, value in options.items():
            if key.strip().casefold() == "size":
                return value
        return fallback_title

    def _extract_color(self, options: dict[str, str], fallback_color: str) -> str:
        for key, value in options.items():
            if key.strip().casefold() in {"color", "colour"}:
                return value
        return fallback_color

    def _infer_color_from_variants(self, variants, url: str) -> str:
        if not variants:
            return url
        title = variants[0].product_title
        if " - " in title:
            return title.split(" - ")[-1].strip()
        slug = url.rstrip("/").split("/")[-1].replace("-", " ")
        parts = slug.split()
        return parts[-1].title() if parts else title
