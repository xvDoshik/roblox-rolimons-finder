from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Iterable

import requests

from sanitizer import InputSanitizer, ItemInputSanitizer, OutputSanitizer

DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.rolimons.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
    ),
}

COPY_VARS = ("all_copies_data", "bc_copies_data", "hoards_data")
SOURCE_CHOICES = ("auto", "all_copies_data", "bc_copies_data", "hoards_data")
IGNORED_PLAYER_IDS = frozenset({1})


@dataclass(frozen=True)
class ItemOwners:
    item_id: int
    item_name: str
    source: str
    owner_ids: frozenset[int]
    owner_names: dict[int, str]
    total_rows: int
    expected_owners: int | None
    complete: bool
    thumbnail_url: str | None = None
    value: int | None = None
    rap: int | None = None

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "item_name": self.item_name,
            "item_url": f"https://www.rolimons.com/item/{self.item_id}",
            "source": self.source,
            "unique_owners": len(self.owner_ids),
            "expected_owners": self.expected_owners,
            "complete": self.complete,
            "rows": self.total_rows,
            "thumbnail_url": self.thumbnail_url,
            "value": self.value,
            "rap": self.rap,
        }


@dataclass(frozen=True)
class IntersectResult:
    item_ids: list[int]
    players: list[dict]
    items: list[dict]
    intersection_count: int

    def to_dict(self) -> dict:
        return {
            "item_ids": self.item_ids,
            "players": self.players,
            "items": self.items,
            "intersection_count": self.intersection_count,
        }


class ItemIdParser:
    @staticmethod
    def parse_many(values: Iterable[str]) -> list[int]:
        cleaned = ItemInputSanitizer.sanitize_many([str(value) for value in values])
        return [int(value) for value in cleaned]

    @staticmethod
    def parse_one(raw: str) -> list[int]:
        cleaned = ItemInputSanitizer.sanitize_token(str(raw))
        return [int(cleaned)]


class RolimonsItemOwnersClient:
    ITEM_URL = "https://www.rolimons.com/item/{item_id}"

    def __init__(self, timeout: float = 30.0, delay: float = 0.35) -> None:
        self._session = requests.Session()
        self._session.headers.update(DEFAULT_HEADERS)
        self._timeout = timeout
        self._delay = delay
        self._last_fetch = 0.0

    def fetch_item_owners(self, item_id: int, source: str = "auto") -> ItemOwners:
        html = self._get_html(item_id)
        if "Just a moment..." in html or "cdn-cgi/challenge-platform" in html:
            raise RuntimeError(
                f"item {item_id}: cloudflare challenge, retry later or use browser cookies"
            )
        details = self._parse_item_details(html)
        parsed = self._parse_copy_blocks(html)
        if source == "auto":
            for var_name in COPY_VARS:
                block = parsed.get(var_name)
                if block and block.get("owner_ids"):
                    return self._build_item_owners(item_id, details, var_name, block)
            raise RuntimeError(f"item {item_id}: no owner data on page")
        block = parsed.get(source)
        if not block:
            raise RuntimeError(f"item {item_id}: missing {source}")
        return self._build_item_owners(item_id, details, source, block)

    def _get_html(self, item_id: int) -> str:
        elapsed = time.monotonic() - self._last_fetch
        if elapsed < self._delay:
            time.sleep(self._delay - elapsed)
        response = self._session.get(
            self.ITEM_URL.format(item_id=item_id),
            timeout=self._timeout,
        )
        self._last_fetch = time.monotonic()
        response.raise_for_status()
        return response.text

    @staticmethod
    def _parse_item_details(html: str) -> dict:
        match = re.search(r"var item_details_data = (\{.*?\});", html)
        if not match:
            return {}
        return json.loads(match.group(1))

    @staticmethod
    def _parse_copy_blocks(html: str) -> dict[str, dict]:
        blocks: dict[str, dict] = {}
        for var_name in COPY_VARS:
            match = re.search(rf"var {var_name} = (\{{.*?\}});", html, re.DOTALL)
            if match:
                blocks[var_name] = json.loads(match.group(1))
        return blocks

    @staticmethod
    def _build_item_owners(
        item_id: int,
        details: dict,
        source: str,
        block: dict,
    ) -> ItemOwners:
        raw_ids = block.get("owner_ids") or []
        raw_names = block.get("owner_names") or []
        owner_ids: set[int] = set()
        owner_names: dict[int, str] = {}
        for index, raw_id in enumerate(raw_ids):
            if raw_id is None:
                continue
            player_id = int(raw_id)
            owner_ids.add(player_id)
            if index < len(raw_names):
                name = raw_names[index]
                if isinstance(name, str) and name:
                    owner_names[player_id] = name
        expected = details.get("owners")
        expected_owners = int(expected) if isinstance(expected, int) else None
        complete = expected_owners is None or len(owner_ids) >= expected_owners
        value = details.get("value")
        rap = details.get("rap")
        return ItemOwners(
            item_id=item_id,
            item_name=str(details.get("item_name") or item_id),
            source=source,
            owner_ids=frozenset(owner_ids),
            owner_names=owner_names,
            total_rows=len(raw_ids),
            expected_owners=expected_owners,
            complete=complete,
            thumbnail_url=details.get("thumbnail_url_lg"),
            value=int(value) if isinstance(value, int) and value > 0 else None,
            rap=int(rap) if isinstance(rap, int) else None,
        )


class OwnerIntersectionService:
    def __init__(self, client: RolimonsItemOwnersClient | None = None) -> None:
        self._client = client or RolimonsItemOwnersClient()

    def intersect(self, item_ids: Iterable[int], source: str = "auto") -> IntersectResult:
        if source not in SOURCE_CHOICES:
            raise ValueError(f"invalid source: {source}")
        ids = [int(item_id) for item_id in item_ids]
        if len(ids) < 2:
            raise ValueError("need at least 2 item ids")

        per_item = [self._client.fetch_item_owners(item_id, source=source) for item_id in ids]
        intersection = set(per_item[0].owner_ids)
        for item in per_item[1:]:
            intersection &= set(item.owner_ids)

        names: dict[int, str] = {}
        for item in per_item:
            names.update(item.owner_names)

        players = [
            {
                "player_id": InputSanitizer.safe_item_id(player_id),
                "name": OutputSanitizer.safe_display_name(names.get(player_id)),
                "profile": f"https://www.rolimons.com/player/{player_id}",
                "roblox_profile": f"https://www.roblox.com/users/{player_id}/profile",
            }
            for player_id in sorted(
                intersection - IGNORED_PLAYER_IDS,
                key=lambda player_id: names.get(player_id, str(player_id)).lower(),
            )
        ]
        return IntersectResult(
            item_ids=ids,
            players=players,
            items=[item.to_dict() for item in per_item],
            intersection_count=len(players),
        )
