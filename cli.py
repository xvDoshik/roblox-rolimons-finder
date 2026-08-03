#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys

from service import ItemIdParser, OwnerIntersectionService, SOURCE_CHOICES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find Rolimons players who own all given limited item ids",
    )
    parser.add_argument("item_ids", nargs="+", help="2+ Roblox asset ids or Rolimons urls")
    parser.add_argument(
        "--source",
        choices=SOURCE_CHOICES,
        default="auto",
        help="owner list source from item page",
    )
    parser.add_argument("--json", action="store_true", help="print json output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    service = OwnerIntersectionService()

    try:
        item_ids = ItemIdParser.parse_many(args.item_ids)
        result = service.intersect(item_ids, source=args.source)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return 0

    print(f"items: {', '.join(str(item_id) for item_id in result.item_ids)}")
    for item in result.items:
        expected = (
            f"/{item['expected_owners']}"
            if item["expected_owners"] is not None
            else ""
        )
        flag = "" if item["complete"] else " INCOMPLETE"
        print(
            f"  {item['item_id']} ({item['item_name']}): "
            f"{item['unique_owners']}{expected} unique owners, "
            f"{item['rows']} rows, source={item['source']}{flag}"
        )
    print(f"intersection: {result.intersection_count} players")
    for player in result.players:
        label = player.get("name") or "?"
        print(f"  {player['player_id']} ({label})  {player['profile']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
