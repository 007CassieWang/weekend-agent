"""
POI repository for local seed data and future external adapters.

Today this repository loads `data/poi_seed.yaml`. Later, Amap/Meituan adapters can
normalize real POIs into the same Activity/Restaurant models without changing the
agent harness.
"""

from __future__ import annotations

from dataclasses import fields
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

import yaml

from schemas import Activity, Location, Restaurant


DEFAULT_POI_SEED_PATH = Path(__file__).parent / "data" / "poi_seed.yaml"
DEFAULT_KB_PATH = Path(__file__).parent / "data" / "poi-knowledge-base-shanghai.yaml"


class PoiAdapter(Protocol):
    """Contract for future external POI sources.

    Adapters should normalize provider-specific fields into the same broad seed
    shape used by data/poi_seed.yaml. The repository can then convert those
    records into Activity/Restaurant models for the existing agent.
    """

    def search(
        self,
        query: str,
        city: str,
        category: Optional[str] = None,
        modifiers: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        ...


ACTIVITY_FIELDS = {field.name for field in fields(Activity)}
RESTAURANT_FIELDS = {field.name for field in fields(Restaurant)}


def _normalize_tags(tags_value: Any) -> List[str]:
    """将知识库三维 tags (attribute/popularity/action) 展平为 List[str]，兼容旧格式。"""
    if isinstance(tags_value, dict):
        flat: List[str] = []
        for category in ("attribute", "popularity", "action"):
            items = tags_value.get(category, [])
            if isinstance(items, list):
                for item in items:
                    if item and item not in flat:
                        flat.append(str(item))
        return flat
    if isinstance(tags_value, list):
        return [str(t) for t in tags_value if t]
    return []


def _filter_model_fields(data: Dict[str, Any], allowed_fields: set[str]) -> Dict[str, Any]:
    return {key: value for key, value in data.items() if key in allowed_fields}


def _attach_extra_fields(model: Any, source: Dict[str, Any], allowed_fields: set[str]) -> Any:
    for key, value in source.items():
        if key not in allowed_fields:
            setattr(model, key, value)
    return model


def _location_from_dict(data: Dict[str, Any]) -> Location:
    return Location(
        name=data.get("name", ""),
        address=data.get("address", ""),
        coordinates=data.get("coordinates"),
        district=data.get("district"),
    )


def _activity_from_dict(data: Dict[str, Any]) -> Activity:
    payload = dict(data)
    payload["location"] = _location_from_dict(payload["location"])
    payload["tags"] = _normalize_tags(payload.get("tags"))
    model_payload = _filter_model_fields(payload, ACTIVITY_FIELDS)
    return _attach_extra_fields(Activity(**model_payload), payload, ACTIVITY_FIELDS)


def _restaurant_from_dict(data: Dict[str, Any]) -> Restaurant:
    payload = dict(data)
    payload["location"] = _location_from_dict(payload["location"])
    payload["tags"] = _normalize_tags(payload.get("tags"))
    model_payload = _filter_model_fields(payload, RESTAURANT_FIELDS)
    return _attach_extra_fields(Restaurant(**model_payload), payload, RESTAURANT_FIELDS)


@lru_cache(maxsize=4)
def load_poi_seed(path: str = str(DEFAULT_POI_SEED_PATH)) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as file:
        payload = yaml.safe_load(file) or {}
    return payload


class PoiRepository:
    """Read-only POI repository backed by the local seed file."""

    def __init__(self, seed_path: Optional[Path] = None):
        self.seed_path = seed_path or DEFAULT_KB_PATH

    def list_activity_dicts(self) -> List[Dict[str, Any]]:
        payload = load_poi_seed(str(self.seed_path))
        return [dict(item) for item in payload.get("activities", [])]

    def list_restaurant_dicts(self) -> List[Dict[str, Any]]:
        payload = load_poi_seed(str(self.seed_path))
        return [dict(item) for item in payload.get("restaurants", [])]

    def list_activities(self) -> List[Activity]:
        return [_activity_from_dict(item) for item in self.list_activity_dicts()]

    def list_restaurants(self) -> List[Restaurant]:
        return [_restaurant_from_dict(item) for item in self.list_restaurant_dicts()]

    def get_activity(self, item_id: str) -> Optional[Activity]:
        for activity in self.list_activities():
            if activity.id == item_id:
                return activity
        return None

    def get_restaurant(self, item_id: str) -> Optional[Restaurant]:
        for restaurant in self.list_restaurants():
            if restaurant.id == item_id:
                return restaurant
        return None


default_poi_repository = PoiRepository()
