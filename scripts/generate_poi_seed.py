"""
使用 DeepSeek 生成大众点评风格的上海本地 POI mock seed 数据。
输出覆盖 product_rules.yaml 中定义的主要类目，名字和质感对标美团/大众点评。
"""

import json
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = PROJECT_ROOT / "config" / "product_rules.yaml"
OUTPUT_PATH = PROJECT_ROOT / "data" / "poi_seed.yaml"

CATEGORIES = {
    "shopping_mall": {"cn": "商场综合体", "count": 6, "type": "mall"},
    "commercial_street": {"cn": "商业街/步行街", "count": 3, "type": "commercial_street"},
    "exhibition": {"cn": "展览/美术馆", "count": 4, "type": "exhibition"},
    "museum": {"cn": "博物馆/科技馆", "count": 3, "type": "museum"},
    "park_outdoor": {"cn": "公园/户外/滨水", "count": 4, "type": "park"},
    "cinema": {"cn": "电影院", "count": 2, "type": "cinema"},
    "ktv_boardgame": {"cn": "KTV/桌游/剧本杀", "count": 3, "type": "ktv"},
    "handicraft_market": {"cn": "手作/市集", "count": 3, "type": "handicraft"},
    "wellness": {"cn": "SPA/书店/放松", "count": 3, "type": "spa"},
}

RESTAURANT_SPECS = [
    ("hotpot", "火锅", 3),
    ("bbq", "烧烤", 2),
    ("japanese", "日料", 2),
    ("cantonese", "粤菜/本帮菜", 3),
    ("western", "西餐", 2),
    ("cafe_dessert", "咖啡/茶馆/甜品", 3),
    ("light_meal", "轻食/健康餐", 2),
    ("street_food", "小吃/夜宵", 2),
    ("exotic", "东南亚/韩料/特色菜", 3),
]

SHANGHAI_DISTRICTS = [
    {"name": "人民广场商圈", "center": [31.232, 121.473], "radius_km": 3},
    {"name": "静安寺商圈", "center": [31.225, 121.448], "radius_km": 3},
    {"name": "徐家汇商圈", "center": [31.195, 121.437], "radius_km": 3},
    {"name": "陆家嘴滨江", "center": [31.240, 121.500], "radius_km": 3},
    {"name": "五角场商圈", "center": [31.298, 121.515], "radius_km": 3},
    {"name": "虹桥天地周边", "center": [31.205, 121.375], "radius_km": 3},
    {"name": "前滩太古里周边", "center": [31.155, 121.483], "radius_km": 3},
    {"name": "北外滩滨水区", "center": [31.252, 121.495], "radius_km": 3},
    {"name": "武康路衡复街区", "center": [31.207, 121.440], "radius_km": 2},
    {"name": "世纪公园周边", "center": [31.208, 121.552], "radius_km": 3},
    {"name": "新天地周边", "center": [31.217, 121.474], "radius_km": 2},
    {"name": "中山公园商圈", "center": [31.220, 121.415], "radius_km": 2},
]


def load_rules():
    with open(RULES_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_activity_prompt(rules: dict, category: str, specs: dict, district: dict) -> str:
    taxonomy = rules.get("local_life_poi_taxonomy", {})
    return f"""你是大众点评上海站的内容编辑。请为"{specs['cn']}"类目生成 {specs['count']} 个真实风格的上海本地活动 POI。

要求：
1. **名字必须像真实上海 POI**，对标大众点评/美团上的实际场所。不要用模板拼接，要用能让上海本地人觉得"我去过"或"听说过"的命名风格。例如：不是"XX购物中心工坊"，而是"环球港""TX淮海""上生新所""西岸美术馆""油罐艺术中心"这种质感。
2. 名字可以是半虚构的——风格真实但具体不存在也没关系，因为我们标注为 mock 数据
3. 商圈限定在：{district['name']}，坐标在 [{district['center'][0]}, {district['center'][1]}] 周边 {district['radius_km']}km 范围内
4. 每个 POI 需要完整的结构化数据

输出 JSON 数组，每个元素格式：
{{
  "id": "act_XXX",
  "name": "POI 名称",
  "type": "{specs['type']}",
  "location": {{
    "name": "同 POI 名称",
    "address": "上海市XX区XX路XX号",
    "coordinates": {{"lat": 31.xxx, "lng": 121.xxx}},
    "district": "{district['name']}"
  }},
  "distance_km": 2-15 之间的数字,
  "duration_minutes": 建议游玩分钟数,
  "suggested_duration_minutes": 同上,
  "child_friendly": true/false,
  "child_min_age": 儿童最低年龄限制，无限制填0,
  "group_friendly": true/false,
  "price_per_person": 人均价格（元）,
  "queue_minutes": 预计排队分钟数,
  "reservation_available": true/false,
  "need_booking": true/false,
  "description": "50字以内的大众点评风格描述",
  "tags": ["3-5个标签，中文"],
  "poi_category": "类目路径，如 商场综合体.购物中心",
  "elder_friendly": true/false,
  "pet_friendly": true/false,
  "noise_level": "low/medium/high",
  "walking_load": "low/medium/high",
  "indoor_outdoor": "indoor/outdoor/mixed",
  "photo_spot": true/false,
  "near_subway": true/false,
  "parking_available": true/false,
  "risk_tags": ["风险标签，如 排队/预约/天气依赖/停车拥堵"],
  "atmosphere_tags": ["氛围标签"],
  "recommendation_reason_seed": "一句话推荐理由"
}}

只输出一个 JSON 对象，格式：{{"items": [上述 POI 对象数组]}}。不要 markdown 代码块。"""


def build_restaurant_prompt(spec: tuple, district: dict) -> str:
    cuisine_type, cuisine_cn, count = spec
    return f"""你是大众点评上海站的美食编辑。请为"{cuisine_cn}"类目生成 {count} 家真实风格的上海本地餐厅。

要求：
1. **名字必须像真实上海餐厅**，对标大众点评/美团上实际存在的店。要有上海本地特色，例如"平成屋""哥老官""东发道""红盔甲""蟹尊苑""%Arabica"这种质感，不是"XX餐厅工坊"。
2. 商圈：{district['name']}，坐标在 [{district['center'][0]}, {district['center'][1]}] 周边 {district['radius_km']}km
3. 需要完整的结构化数据

输出 JSON 数组，每个元素格式：
{{
  "id": "rest_XXX",
  "name": "餐厅名称",
  "type": "{cuisine_type}",
  "cuisine_type": "{cuisine_cn}",
  "location": {{
    "name": "同餐厅名称",
    "address": "上海市XX区XX路XX号",
    "coordinates": {{"lat": 31.xxx, "lng": 121.xxx}},
    "district": "{district['name']}"
  }},
  "distance_km": 1-12 之间的数字,
  "child_friendly": true/false,
  "diet_friendly": true/false,
  "group_friendly": true/false,
  "price_per_person": 人均价格（元）,
  "queue_minutes": 预计排队分钟数,
  "reservation_available": true/false,
  "need_booking": true/false,
  "description": "50字以内的大众点评风格描述，突出特色和必点菜",
  "signature_dishes": ["2-4道招牌菜"],
  "tags": ["3-5个标签"],
  "poi_category": "美食.{cuisine_cn}",
  "risk_tags": ["风险标签"],
  "atmosphere_tags": ["氛围标签"],
  "recommendation_reason_seed": "一句话推荐理由"
}}

只输出一个 JSON 对象，格式：{{"items": [上述餐厅对象数组]}}。不要 markdown 代码块。"""


def call_deepseek(prompt: str, max_tokens: int = 8192) -> list:
    client = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com/v1",
    )
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "你是大众点评/美团上海站高级内容编辑，熟悉上海本地生活消费场景。你输出的 POI 数据风格真实、专业。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
        max_tokens=max_tokens,
        timeout=30,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines)
    data = json.loads(raw)
    # Handle both {"items": [...]} and direct [...] formats
    if isinstance(data, list):
        return data
    for key in data:
        if isinstance(data[key], list):
            return data[key]
    return [data]


def assign_ids(items: list, prefix: str) -> list:
    for i, item in enumerate(items):
        item["id"] = f"{prefix}{i + 1:03d}"
    return items


def main():
    rules = load_rules()

    all_activities = []
    all_restaurants = []

    print("=== 生成活动 POI ===")
    for cat_key, specs in CATEGORIES.items():
        district = SHANGHAI_DISTRICTS[len(all_activities) % len(SHANGHAI_DISTRICTS)]
        prompt = build_activity_prompt(rules, cat_key, specs, district)
        print(f"  生成 {specs['cn']} x {specs['count']}...", end=" ")
        try:
            items = call_deepseek(prompt)
            print(f"√ 获得 {len(items)} 条")
            all_activities.extend(items)
        except Exception as e:
            print(f"× 失败: {e}")

    print(f"\n活动总计: {len(all_activities)} 条")

    print("\n=== 生成餐厅 POI ===")
    for spec in RESTAURANT_SPECS:
        district = SHANGHAI_DISTRICTS[len(all_restaurants) % len(SHANGHAI_DISTRICTS)]
        prompt = build_restaurant_prompt(spec, district)
        cuisine_cn = spec[1]
        count = spec[2]
        print(f"  生成 {cuisine_cn} x {count}...", end=" ")
        try:
            items = call_deepseek(prompt)
            print(f"√ 获得 {len(items)} 条")
            all_restaurants.extend(items)
        except Exception as e:
            print(f"× 失败: {e}")

    print(f"\n餐厅总计: {len(all_restaurants)} 条")

    # Assign sequential IDs
    all_activities = assign_ids(all_activities, "act_")
    all_restaurants = assign_ids(all_restaurants, "rest_")

    # Build output
    output = {
        "version": 3,
        "description": "大众点评风格的上海本地生活 mock POI seed。名称对标真实大众点评/美团 POI 质感，用于产品验证和评分测试。",
        "metadata": {
            "city": "上海",
            "source": "deepseek_generated_mock",
            "real_world_claims": False,
            "generator": "scripts/generate_poi_seed.py",
        },
        "activities": all_activities,
        "restaurants": all_restaurants,
    }

    # Add YAML anchors for tags to keep file size reasonable
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        yaml.dump(output, f, allow_unicode=True, sort_keys=False, default_flow_style=False, width=200)

    print(f"\n已写入 {OUTPUT_PATH}")
    print(f"文件大小: {OUTPUT_PATH.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
