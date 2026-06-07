#!/usr/bin/env python3
"""
Expand restaurant coupons in poi-knowledge-base-shanghai.yaml with diverse
group-size packages for better slot-aware recommendation matching.

Adds: 单人套餐, 2-3人小聚套餐, 3-4人家庭套餐, 6-8人聚会套餐, 浪漫约会套餐
based on each restaurant's character (cuisine type, price level, family-friendliness, etc.)
"""

import copy
import sys
from pathlib import Path

import yaml

KB_PATH = Path(__file__).parent.parent / "data" / "poi-knowledge-base-shanghai.yaml"

# ---- Coupon templates by restaurant character ----

def make_coupon(title, platform, original_price, coupon_price, description, valid_until="2026-06-30"):
    return {
        "title": title,
        "platform": platform,
        "original_price": original_price,
        "coupon_price": coupon_price,
        "description": description,
        "valid_until": valid_until,
    }


def expand_restaurant_coupons(restaurant):
    """Given a restaurant dict, return expanded coupons list."""
    existing = restaurant.get("coupons", []) or []
    existing_titles = {c["title"] for c in existing}
    name = restaurant.get("name", "")
    cuisine = restaurant.get("cuisine_type", "")
    ppp = restaurant.get("price_per_person", 100)
    child_friendly = restaurant.get("child_friendly", False)
    group_friendly = restaurant.get("group_friendly", False)
    diet_friendly = restaurant.get("diet_friendly", False)
    tags_attr = []
    tags = restaurant.get("tags", {})
    if isinstance(tags, dict):
        tags_attr = tags.get("attribute", [])
    elif isinstance(tags, list):
        tags_attr = tags

    new_coupons = list(existing)  # keep existing

    def add_if_missing(title, platform, orig, price, desc):
        if title not in existing_titles:
            new_coupons.append(make_coupon(title, platform, orig, price, desc))
            existing_titles.add(title)

    # ---- Determine which coupon types to add based on restaurant profile ----

    # 1. 单人套餐 — for solo-friendly restaurants
    solo_friendly = any(kw in str(tags_attr) for kw in ["一人食", "一人食友好", "白领午餐", "平价"])
    cp_pct = 0.65  # coupon discount percentage

    if solo_friendly or cuisine in ("咖啡/茶馆/甜品", "轻食/健康餐", "小吃/夜宵"):
        price_1 = int(ppp * cp_pct)
        orig_1 = int(ppp * 1.3)
        add_if_missing(
            f"单人{'轻食' if '轻食' in cuisine else '下午茶' if '咖啡' in cuisine or '甜品' in cuisine or '茶馆' in cuisine else '夜宵' if '夜宵' in cuisine else '体验'}套餐",
            "meituan", orig_1, price_1,
            f"含1份主菜+1杯饮品"
        )

    # 2. 2-3人小聚套餐 — for most group-friendly restaurants (not ultra-high-end, not cafes)
    if group_friendly and cuisine not in ("咖啡/茶馆/甜品",):
        price_23 = int(ppp * 2.5 * cp_pct)
        orig_23 = int(ppp * 2.5 * 1.3)
        # Customize name and price based on cuisine
        if cuisine == "火锅":
            add_if_missing("2-3人小聚套餐", "meituan", int(ppp * 2.5 * 1.35), int(ppp * 2.5 * 0.72),
                          "含招牌锅底+3荤3素+饮品，2-3人刚好")
        elif cuisine == "烧烤":
            add_if_missing("2-3人小聚套餐", "meituan", int(ppp * 2.5 * 1.35), int(ppp * 2.5 * 0.72),
                          "含招牌烤串+小食+饮品，2-3人畅吃")
        elif cuisine == "日料":
            add_if_missing("2-3人品鲜套餐", "meituan", int(ppp * 2.5 * 1.3), int(ppp * 2.5 * 0.7),
                          "含刺身拼盘+寿司+小食+饮品")
        elif "粤菜" in cuisine or "本帮菜" in cuisine:
            add_if_missing("2-3人品鉴套餐", "meituan", int(ppp * 2.5 * 1.3), int(ppp * 2.5 * 0.72),
                          "含招牌菜3道+主食+饮品，精致小聚")
        elif cuisine == "西餐":
            add_if_missing("2-3人小聚套餐", "meituan", int(ppp * 2.5 * 1.3), int(ppp * 2.5 * 0.75),
                          "含主菜+前菜+甜品+饮品")
        elif "东南亚" in cuisine or "韩料" in cuisine or "特色菜" in cuisine:
            add_if_missing("2-3人小聚套餐", "meituan", int(ppp * 2.5 * 1.3), int(ppp * 2.5 * 0.72),
                          "含招牌菜+主食+饮品，2-3人尝鲜刚好")
        else:
            add_if_missing("2-3人小聚套餐", "meituan", orig_23, price_23,
                          "含招牌菜+饮品+主食，2-3人小聚")

    # 3. 3-4人家庭套餐 — for family-friendly restaurants
    if child_friendly and cuisine not in ("咖啡/茶馆/甜品", "轻食/健康餐"):
        if cuisine == "火锅":
            add_if_missing("3-4人家庭套餐", "meituan", int(ppp * 3.5 * 1.35), int(ppp * 3.5 * 0.7),
                          "含招牌锅底+5荤4素+儿童小食+饮品，全家吃饱")
        elif "粤菜" in cuisine or "本帮菜" in cuisine:
            add_if_missing("3-4人家庭套餐", "meituan", int(ppp * 3.5 * 1.3), int(ppp * 3.5 * 0.7),
                          "含招牌菜4道+主食+儿童餐+饮品，老少皆宜")
        elif cuisine == "烧烤":
            add_if_missing("3-4人家庭套餐", "meituan", int(ppp * 3.5 * 1.35), int(ppp * 3.5 * 0.7),
                          "含招牌烤串+儿童套餐+小食+饮品，全家撸串")
        elif "东南亚" in cuisine or "韩料" in cuisine or "特色菜" in cuisine:
            add_if_missing("3-4人家庭套餐", "meituan", int(ppp * 3.5 * 1.3), int(ppp * 3.5 * 0.7),
                          "含招牌菜+主食+儿童份+饮品，全家共享")
        else:
            add_if_missing("3-4人家庭套餐", "meituan", int(ppp * 3.5 * 1.3), int(ppp * 3.5 * 0.7),
                          "含招牌菜+主食+饮品，适合3-4人家庭")

    # 4. 6-8人聚会套餐 — for large-group-friendly, social restaurants
    social_cuisines = {"火锅", "烧烤", "小吃/夜宵"}
    is_social = cuisine in social_cuisines or any(
        kw in str(tags_attr) for kw in ["聚餐", "聚会", "团建", "宴请", "商务宴请"]
    )
    if group_friendly and (is_social or cuisine in ("粤菜/本帮菜", "东南亚/韩料/特色菜", "西餐")):
        if cuisine == "火锅":
            add_if_missing("6-8人聚会套餐", "meituan", int(ppp * 7 * 1.3), int(ppp * 7 * 0.68),
                          "含双锅底+10荤8素+饮品畅饮，6-8人嗨吃")
        elif cuisine == "烧烤":
            add_if_missing("6-8人聚会套餐", "meituan", int(ppp * 7 * 1.3), int(ppp * 7 * 0.68),
                          "含招牌烤串大份+海鲜拼盘+啤酒畅饮，6-8人嗨聚")
        elif "粤菜" in cuisine or "本帮菜" in cuisine:
            add_if_missing("6-8人聚会套餐", "meituan", int(ppp * 7 * 1.25), int(ppp * 7 * 0.68),
                          "含招牌菜6道+主食+饮品，圆桌聚会")
        elif "东南亚" in cuisine or "韩料" in cuisine or "特色菜" in cuisine:
            add_if_missing("6-8人聚会套餐", "meituan", int(ppp * 7 * 1.25), int(ppp * 7 * 0.68),
                          "含招牌菜大份+主食+饮品畅饮，6-8人欢聚")
        elif cuisine == "小吃/夜宵":
            add_if_missing("6-8人聚会套餐", "meituan", int(ppp * 7 * 1.3), int(ppp * 7 * 0.68),
                          "含招牌菜大份+小食拼盘+饮品，6-8人夜宵局")
        elif cuisine == "西餐":
            add_if_missing("6-8人聚会套餐", "meituan", int(ppp * 7 * 1.25), int(ppp * 7 * 0.7),
                          "含主菜+前菜拼盘+甜品+饮品，长桌聚会")
        else:
            add_if_missing("6-8人聚会套餐", "meituan", int(ppp * 7 * 1.25), int(ppp * 7 * 0.7),
                          "含招牌菜+主食+饮品畅饮，6-8人聚会")

    # 5. 浪漫约会套餐 — for romantic/date-worthy restaurants
    is_romantic = any(kw in str(tags_attr) for kw in ["浪漫", "约会圣地", "约会", "情侣", "江景/景观", "禅意雅致"])
    if is_romantic or (cuisine in ("西餐", "日料") and ppp >= 200):
        add_if_missing("浪漫约会双人套餐", "dianping", int(ppp * 2 * 1.25), int(ppp * 2 * 0.7),
                      "含双人招牌菜+甜品+配饮，氛围满分")

    # 6. 单人体验 — for Japanese omakase / solo-friendly upscale
    if cuisine == "日料" and ppp >= 150:
        add_if_missing("单人Omakase体验", "dianping", int(ppp * 1.3), int(ppp * 0.72),
                      "含前菜+刺身+寿司+甜品，一人食也精致")

    return new_coupons


def main():
    with open(KB_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    restaurants = data.get("restaurants", [])
    expanded_count = 0

    for rest in restaurants:
        old_count = len(rest.get("coupons", []) or [])
        rest["coupons"] = expand_restaurant_coupons(rest)
        new_count = len(rest["coupons"])
        added = new_count - old_count
        if added > 0:
            expanded_count += 1
            print(f"  {rest['id']} {rest['name']}: {old_count} → {new_count} coupons (+{added})")

    # Write back with consistent formatting
    with open(KB_PATH, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False, width=120)

    print(f"\nDone. Expanded {expanded_count}/{len(restaurants)} restaurants.")


if __name__ == "__main__":
    main()
