from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class WatchConfig:
    name: str
    url: str
    size: str
    color: str
    recipient: str = ""
    length: str | None = None
    check_interval_minutes: int = 10


@dataclass
class AppConfig:
    state_file: Path
    watchers: list[WatchConfig]


def load_config(path: str) -> AppConfig:
    raw = json.loads(Path(path).read_text())
    state_file = Path(raw.get("state_file", "state.json"))
    watchers = [_load_watch(item) for item in raw.get("watchers", [])]
    if not watchers:
        raise ValueError("Config must include at least one watcher.")
    return AppConfig(state_file=state_file, watchers=watchers)


def _load_watch(item: dict[str, Any]) -> WatchConfig:
    required = ("name", "url", "size", "color")
    missing = [key for key in required if not item.get(key)]
    if missing:
        raise ValueError(f"Watcher is missing required fields: {', '.join(missing)}")
    return WatchConfig(
        name=str(item["name"]),
        url=str(item["url"]),
        size=str(item["size"]),
        color=str(item["color"]),
        recipient=str(item.get("recipient", "")),
        length=str(item["length"]) if item.get("length") else None,
        check_interval_minutes=int(item.get("check_interval_minutes", 10)),
    )
