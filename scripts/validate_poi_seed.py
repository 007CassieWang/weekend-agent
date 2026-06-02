#!/usr/bin/env python3
"""Validate local POI seed coverage and required fields."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List

import yaml


SEED_PATH = Path(__file__).resolve().parents[1] / "data" / "poi_seed.yaml"

REQUIRED_COMMON_FIELDS = {
    "id",
    "name",
    "type",
    "poi_category",
    "location",
    "distance_km",
    "price_per_person",
    "suggested_duration_minutes",
    "queue_minutes",
    "need_booking",
    "child_friendly",
    "elder_friendly",
    "pet_friendly",
    "group_friendly",
    "noise_level",
    "walking_load",
    "indoor_outdoor",
    "photo_spot",
    "near_subway",
    "parking_available",
    "risk_tags",
    "atmosphere_tags",
    "quality_tags",
    "best_for",
    "description",
    "recommendation_reason_seed",
}

REQUIRED_LOCATION_FIELDS = {"name", "address", "district"}


def load_seed() -> Dict[str, Any]:
    with open(SEED_PATH, "r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def iter_items(seed: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    yield from seed.get("activities", [])
    yield from seed.get("restaurants", [])


def validate_required_fields(items: List[Dict[str, Any]]) -> List[str]:
    errors = []
    seen_ids = set()
    for index, item in enumerate(items, start=1):
        item_id = item.get("id", f"<missing-{index}>")
        missing = sorted(REQUIRED_COMMON_FIELDS - set(item))
        if missing:
            errors.append(f"{item_id}: missing fields {missing}")
        location = item.get("location") or {}
        missing_location = sorted(REQUIRED_LOCATION_FIELDS - set(location))
        if missing_location:
            errors.append(f"{item_id}: missing location fields {missing_location}")
        if item_id in seen_ids:
            errors.append(f"{item_id}: duplicate id")
        seen_ids.add(item_id)
    return errors


def main() -> int:
    seed = load_seed()
    activities = seed.get("activities", [])
    restaurants = seed.get("restaurants", [])
    items = list(iter_items(seed))
    category_counts = Counter((item.get("poi_category") or "unknown").split(".")[0] for item in items)

    errors = validate_required_fields(items)
    if len(items) < 150:
        errors.append(f"total POI count too low: {len(items)}")
    if len(activities) < 100:
        errors.append(f"activity count too low: {len(activities)}")
    if len(restaurants) < 60:
        errors.append(f"restaurant count too low: {len(restaurants)}")

    print(f"seed_version: {seed.get('version')}")
    print(f"activities: {len(activities)}")
    print(f"restaurants: {len(restaurants)}")
    print(f"total: {len(items)}")
    print("category_counts:")
    for category, count in sorted(category_counts.items()):
        print(f"  {category}: {count}")

    if errors:
        print("errors:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("validation: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
