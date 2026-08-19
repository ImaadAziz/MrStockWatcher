from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_ROOT = "https://api.telegram.org"


@dataclass
class TelegramUpdate:
    update_id: int
    chat_id: int
    text: str


class TelegramBotClient:
    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("Telegram bot token is required.")
        self.token = token

    def get_me(self) -> dict[str, Any]:
        response = self._request("getMe", {})
        return dict(response.get("result", {}))

    def get_updates(self, offset: int | None = None, timeout: int = 20) -> list[TelegramUpdate]:
        payload: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        response = self._request("getUpdates", payload)
        updates: list[TelegramUpdate] = []
        for item in response.get("result", []):
            message = item.get("message") or item.get("edited_message") or {}
            chat = message.get("chat") or {}
            text = message.get("text")
            chat_id = chat.get("id")
            update_id = item.get("update_id")
            if text is None or chat_id is None or update_id is None:
                continue
            updates.append(TelegramUpdate(update_id=int(update_id), chat_id=int(chat_id), text=str(text)))
        return updates

    def send_message(self, chat_id: int, text: str) -> None:
        self._request("sendMessage", {"chat_id": chat_id, "text": text})

    def _request(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        encoded = urlencode(payload).encode("utf-8")
        request = Request(
            f"{API_ROOT}/bot{self.token}/{method}",
            data=encoded,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
        data = json.loads(raw)
        if not data.get("ok"):
            raise ValueError(f"Telegram API call failed for {method}: {data}")
        return data
