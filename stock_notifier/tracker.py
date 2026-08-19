from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .config import WatchConfig


USER_AGENT = "stock-notifier/1.0 (+https://local-machine)"


@dataclass
class StockStatus:
    in_stock: bool
    product_title: str
    variant_id: str | None
    variant_label: str
    source: str


@dataclass
class VariantRecord:
    product_title: str
    product_handle: str
    variant_id: str
    title: str
    available: bool
    options: dict[str, str]


class ProductTracker:
    def fetch_status(self, watch: WatchConfig) -> StockStatus:
        product_json = self._fetch_product_json(watch.url)
        if product_json is not None:
            return self._status_from_product_json(product_json, watch)
        html = self._fetch_text(watch.url)
        return self._status_from_html(html, watch)

    def list_variants(self, url: str) -> list[VariantRecord]:
        product = self._fetch_product_json(url)
        if product is None:
            raise ValueError("This page did not expose a Shopify product JSON payload.")

        option_names = [str(option.get("name", "")).strip() for option in product.get("options", [])]
        product_title = str(product.get("title") or "")
        product_handle = str(product.get("handle") or "")
        records: list[VariantRecord] = []

        for variant in product.get("variants", []):
            option_map: dict[str, str] = {}
            for index, option_name in enumerate(option_names, start=1):
                value = variant.get(f"option{index}")
                if option_name and value is not None:
                    option_map[option_name] = str(value)
            records.append(
                VariantRecord(
                    product_title=product_title,
                    product_handle=product_handle,
                    variant_id=str(variant.get("id")),
                    title=str(variant.get("title") or ""),
                    available=bool(variant.get("available")),
                    options=option_map,
                )
            )

        return records

    def _fetch_product_json(self, url: str) -> dict[str, Any] | None:
        parsed = urlparse(url)
        handle = parsed.path.rstrip("/").split("/")[-1]
        if not handle:
            return None
        product_json_url = f"{parsed.scheme}://{parsed.netloc}/products/{handle}.js"
        try:
            return json.loads(self._fetch_text(product_json_url))
        except (HTTPError, URLError, json.JSONDecodeError):
            return None

    def _fetch_text(self, url: str) -> str:
        request = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8", errors="replace")

    def _status_from_product_json(self, product: dict[str, Any], watch: WatchConfig) -> StockStatus:
        variant = self._find_variant(product, watch)
        if variant is None:
            details = [f"size '{watch.size}'", f"color '{watch.color}'"]
            if watch.length:
                details.append(f"length '{watch.length}'")
            raise ValueError(f"Could not find a matching variant for {', '.join(details)}.")
        product_title = str(product.get("title") or watch.name)
        variant_title = str(variant.get("title") or watch.size)
        return StockStatus(
            in_stock=bool(variant.get("available")),
            product_title=product_title,
            variant_id=str(variant.get("id")) if variant.get("id") is not None else None,
            variant_label=variant_title,
            source="product_json",
        )

    def _find_variant(self, product: dict[str, Any], watch: WatchConfig) -> dict[str, Any] | None:
        options = [str(option.get("name", "")).strip().lower() for option in product.get("options", [])]
        variants = product.get("variants", [])

        size_names = {"size"}
        color_names = {"color", "colour"}
        length_names = {"length", "inseam"}

        def option_map(variant: dict[str, Any]) -> dict[str, str]:
            mapped: dict[str, str] = {}
            for index, option_name in enumerate(options, start=1):
                value = variant.get(f"option{index}")
                if value is not None:
                    mapped[option_name] = str(value)
            return mapped

        requested_color = watch.color.casefold()
        requested_size = watch.size.casefold()
        requested_length = watch.length.casefold() if watch.length else ""
        has_color_option = any(name in color_names for name in options)
        has_size_option = any(name in size_names for name in options)
        has_length_option = any(name in length_names for name in options)

        if has_length_option and not requested_length:
            raise ValueError("This product requires a length option, but the watch config did not provide one.")

        if not has_color_option:
            page_color = self._infer_page_color(product, watch.url)
            if page_color.casefold() != requested_color:
                raise ValueError(
                    f"Requested color '{watch.color}' does not match page color '{page_color}'."
                )

        for variant in variants:
            mapped = option_map(variant)

            if has_color_option:
                color_value = next((mapped[name] for name in mapped if name in color_names), "")
                if color_value.casefold() != requested_color:
                    continue

            if has_size_option:
                size_value = next((mapped[name] for name in mapped if name in size_names), "")
                if size_value.casefold() != requested_size:
                    continue

            if has_length_option:
                length_value = next((mapped[name] for name in mapped if name in length_names), "")
                if length_value.casefold() != requested_length:
                    continue

            return variant

        for variant in variants:
            title = str(variant.get("title", ""))
            title_casefold = title.casefold()
            if requested_size not in title_casefold:
                continue
            if requested_length and requested_length not in title_casefold:
                continue
            if has_color_option and requested_color not in title_casefold:
                continue
            if not has_color_option or requested_color in title_casefold:
                return variant
        return None

    def _infer_page_color(self, product: dict[str, Any], url: str) -> str:
        for field in ("title", "handle"):
            value = product.get(field)
            if not value:
                continue
            match = re.search(r"-\s*([A-Za-z][A-Za-z\s]+)$", str(value))
            if match:
                return match.group(1).strip()

        slug = urlparse(url).path.rstrip("/").split("/")[-1]
        cleaned = slug.replace("-", " ")
        parts = cleaned.split()
        if parts:
            return parts[-1].title()
        return "Unknown"

    def _status_from_html(self, html: str, watch: WatchConfig) -> StockStatus:
        normalized = html.casefold()
        in_stock = "sold out" not in normalized and "add to bag" in normalized
        title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        title = unescape(title_match.group(1).strip()) if title_match else watch.name
        return StockStatus(
            in_stock=in_stock,
            product_title=title,
            variant_id=None,
            variant_label=_fallback_variant_label(watch),
            source="html_fallback",
        )


def _fallback_variant_label(watch: WatchConfig) -> str:
    parts = [watch.color, watch.size]
    if watch.length:
        parts.append(watch.length)
    return " / ".join(parts)
