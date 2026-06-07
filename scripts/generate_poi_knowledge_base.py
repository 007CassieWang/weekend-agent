#!/usr/bin/env python3
"""
POI 知识库生成器 — 读取 poi_seed.yaml，为每个 POI 补充 5 个扩展字段：
  1. tags 三维：attribute / popularity / action
  2. sub_facilities（仅活动 POI）
  3. coupons
  4. seasonal_events（仅活动 POI）
  5. nearby_dining（仅活动 POI）

执行：python3 scripts/generate_poi_knowledge_base.py
输出：data/poi-knowledge-base-shanghai.yaml
"""

import copy
import random
import yaml
import sys
import os

# ============================================================
# 全局配置
# ============================================================
CURRENT_DATE = "2026-06-04"
VALID_UNTIL_DEFAULT = "2026-06-30"
VALID_UNTIL_JULY = "2026-07-15"
VALID_UNTIL_AUGUST = "2026-08-31"
VALID_UNTIL_SEPTEMBER = "2026-09-30"
random.seed(20260604)

# ============================================================
# 一、tags 三维迁移
# ============================================================

# --- 参考词库 ---
ATTR_WORD_BANK = {
    "人群适配": ["亲子友好", "全年龄", "宠物友好", "长者友好", "朋友聚会", "情侣约会", "一人食", "团建首选"],
    "空间类型": ["室内恒温", "户外", "半户外", "有包间", "开放式", "弄堂小店", "商场内", "江景/景观", "街区式"],
    "氛围感受": ["文艺复古", "安静治愈", "热闹市井", "时尚潮流", "禅意雅致", "小清新", "浪漫", "烟火气"],
    "出行便利": ["地铁直达", "有停车场", "免费开放", "步行可达", "停车方便"],
    "餐饮特征": ["下午茶", "夜宵", "减脂友好", "老字号", "网红打卡", "一人食友好"],
    "体感强度": ["低强度轻松", "中等互动", "高强度放电", "步行较多"],
}

POP_WORD_BANK = [
    "小红书亲子Top1", "大众点评4.8分", "必吃榜", "上海最热", "排队王",
    "出片率最高", "上海唯一", "衡复街区唯一影院", "市区唯一湿地",
    "历史建筑", "百年老街", "30年老店", "文物保护单位", "衡复风貌",
    "石库门建筑", "遛娃天花板", "本帮菜标杆", "孩子玩到不想走",
    "比科技馆还好玩", "6月限定特展", "夏日限定", "新开业", "刚翻新",
    "上海独有", "米其林", "人民广场地标", "吃喝玩乐一站式搞定",
]

ACTION_WORD_BANK = {
    "预订": ["需预约", "必须预约", "周末需提前3天", "当日可取号", "现场购票即可"],
    "优惠": ["有团购", "有亲子票", "有停车券", "有午市套餐", "有双人套餐", "有4人套餐"],
    "时效": ["限时特展", "当日有效", "周末才开放"],
    "执行提示": ["建议线上购票", "停车X元/小时"],
}


def _tag_in_attr(attr_list: list, keyword: str) -> bool:
    return any(keyword in a for a in attr_list)


def build_tags_3d(poi: dict, is_restaurant: bool = False) -> dict:
    """将旧 tags/atmosphere_tags/risk_tags/recommendation_reason_seed 迁移为三维 tags。"""
    old_tags = poi.get("tags", []) or []
    old_atmo = poi.get("atmosphere_tags", []) or []
    old_risk = poi.get("risk_tags", []) or []
    old_rec = poi.get("recommendation_reason_seed", "")
    poi_cat = poi.get("poi_category", "")
    poi_type = poi.get("type", "")

    attr = list(old_tags)

    # 迁移 atmosphere_tags
    atmo_to_attr = {
        "时尚": "时尚潮流", "热闹": "热闹市井", "家庭": "亲子友好", "复古": "文艺复古",
        "潮流": "时尚潮流", "休闲": "安静治愈", "日常": "烟火气", "自然": "户外",
        "安静": "安静治愈", "文艺": "文艺复古", "怀旧": "文艺复古", "科技感": "时尚潮流",
        "童趣": "亲子友好", "教育": "亲子友好", "清新": "小清新", "宁静": "安静治愈",
        "活力": "时尚潮流", "运动": "中等互动", "刺激": "中等互动", "烧脑": "中等互动",
        "沉浸": "时尚潮流", "剧情": "时尚潮流", "精致": "禅意雅致", "优雅": "禅意雅致",
        "治愈": "安静治愈", "高端": "禅意雅致", "小清新": "小清新", "浪漫": "浪漫",
        "梦幻": "浪漫", "艺术": "文艺复古", "高级": "禅意雅致",
        "知识": "亲子友好", "求知": "亲子友好", "亲子": "亲子友好",
        "温馨": "安静治愈", "干净": "安静治愈", "烟火气": "烟火气",
        "接地气": "烟火气", "家庭友好": "亲子友好", "江景": "江景/景观",
        "简约": "小清新", "商务": "禅意雅致", "传统": "文艺复古",
        "日式": "安静治愈", "市井": "烟火气", "开放厨房": "开放式",
        "吧台座": "一人食友好",
        # 餐饮特有
        "文艺小资": "文艺复古", "日式禅意": "禅意雅致",
        "有包间": "有包间",
    }
    for a in old_atmo:
        mapped = atmo_to_attr.get(a, a)
        if mapped not in attr:
            attr.append(mapped)

    # 补充从 poi_category 末级分类
    if poi_cat:
        last_cat = poi_cat.split(".")[-1] if "." in poi_cat else poi_cat
        if last_cat not in attr:
            attr.append(last_cat)

    # 从核心字段补 attribute
    if poi.get("child_friendly"):
        if "亲子友好" not in attr:
            attr.append("亲子友好")
    if poi.get("pet_friendly"):
        if "宠物友好" not in attr:
            attr.append("宠物友好")
    if poi.get("elder_friendly"):
        if "长者友好" not in attr:
            attr.append("长者友好")
    if poi.get("group_friendly"):
        if "朋友聚会" not in attr and not is_restaurant:
            attr.append("朋友聚会")
    if poi.get("near_subway"):
        if "地铁直达" not in attr:
            attr.append("地铁直达")
    if poi.get("parking_available"):
        if "有停车场" not in attr:
            attr.append("有停车场")
    if poi.get("indoor_outdoor") == "indoor":
        if "室内恒温" not in attr:
            attr.append("室内恒温")
    elif poi.get("indoor_outdoor") == "outdoor":
        if "户外" not in attr:
            attr.append("户外")
    elif poi.get("indoor_outdoor") == "mixed":
        if "半户外" not in attr:
            attr.append("半户外")

    # 体感强度
    walking = poi.get("walking_load", "low")
    noise = poi.get("noise_level", "medium")
    if walking == "high":
        if "步行较多" not in attr:
            attr.append("步行较多")
    if walking == "low" and noise == "low":
        if "低强度轻松" not in attr:
            attr.append("低强度轻松")
    if noise == "high":
        if "中等互动" not in attr:
            attr.append("中等互动")

    # 去重
    attr = list(dict.fromkeys(attr))

    # --- popularity ---
    pop = []
    rec_lower = old_rec.lower() if old_rec else ""

    # 从 poi_category 和 type 推导
    type_cat_map = {
        "mall": ["吃喝玩乐一站式搞定"],
        "museum": ["寓教于乐"],
        "exhibition": ["出片率最高"],
        "park": ["免费开放"],
        "cinema": ["历史建筑"],
        "ktv": ["聚会首选"],
        "handicraft": ["文艺打卡地"],
        "spa": ["小众宝藏"],
        "commercial_street": ["网红打卡"],
        "hotpot": ["必吃榜", "排队王"],
        "bbq": ["排队王"],
        "japanese": ["大众点评4.8分"],
        "cantonese": ["本帮菜标杆", "必吃榜"],
        "western": ["米其林"],
        "cafe_dessert": ["网红打卡", "出片率最高"],
        "light_meal": ["减脂友好"],
        "street_food": ["夜宵必吃", "排队王"],
        "exotic": ["排队王"],
         "桌游": ["团建首选"],
         "剧本杀": ["沉浸式体验标杆"],
    }
    for entry in type_cat_map.get(poi_type, []):
        if entry not in pop:
            pop.append(entry)

    # 从 old_rec 拆解
    if "小红书" in rec_lower or "必打卡" in rec_lower or "打卡" in rec_lower:
        if "网红打卡" not in pop and poi_type not in ("cafe_dessert",):
            pop.append("网红打卡")
    if "排" in rec_lower and "队" in rec_lower:
        if "排队王" not in pop:
            pop.append("排队王")
    if "top" in rec_lower or "Top" in rec_lower or "必" in rec_lower:
        if "必吃榜" not in pop and is_restaurant:
            pop.append("必吃榜")

    # 从 name/description 提取独特性
    name_desc = (poi.get("name", "") + poi.get("description", "")).lower()
    if "历史" in name_desc or "百年" in name_desc or "老" in name_desc:
        if "历史建筑" not in pop:
            pop.append("历史建筑")
    if "唯一" in name_desc:
        if "上海唯一" not in pop:
            pop.append("上海唯一")
    if "衡" in name_desc or "武康" in name_desc:
        if "衡复风貌" not in pop:
            pop.append("衡复风貌")
    if "石库门" in name_desc:
        if "石库门建筑" not in pop:
            pop.append("石库门建筑")
    if "免费" in name_desc:
        if "免费开放" not in pop:
            pop.append("免费开放")
    if "米其林" in name_desc:
        if "米其林" not in pop:
            pop.append("米其林")

    # 从 old_rec 提取推荐语核心（不超过3个）
    if old_rec and len(pop) < 3:
        pop.append(old_rec)

    pop = list(dict.fromkeys(pop))

    # --- action ---
    action = []

    # need_booking → 预订类
    if poi.get("need_booking"):
        if "需预约" not in action:
            action.append("需预约")
    if poi.get("reservation_available"):
        if "当日可取号" not in action:
            action.append("当日可取号")

    # risk_tags → 执行提示
    for r in old_risk:
        if "停车" in r:
            if poi.get("parking_available"):
                if "有停车券" not in action:
                    action.append("有停车券")
        if "排队" in r:
            queue_m = poi.get("queue_minutes", 0)
            if queue_m and queue_m >= 60:
                qtip = f"周末排队约{queue_m}分钟"
                if not any(qtip in str(a) for a in action):
                    action.append(qtip)
            elif "需预约" not in action:
                action.append("需预约")
        if "预约" in r:
            if "需预约" not in action:
                action.append("需预约")
        if "天气" in r and "天气依赖" not in str(action):
            pass

    # 补充：非 risk_tags 但排队时间长（>=60min）的也应提示
    queue_m = poi.get("queue_minutes", 0)
    if queue_m and queue_m >= 60:
        qtip = f"周末排队约{queue_m}分钟"
        if not any(qtip in str(a) for a in action):
            action.append(qtip)

    # 基础执行提示
    if poi.get("parking_available"):
        if not _tag_in_attr(action, "停车"):
            action.append("有停车场")
    if not poi.get("parking_available") and poi.get("near_subway", False):
        if "地铁直达" not in [str(x) for x in action]:
            pass

    action = list(dict.fromkeys(action))

    return {
        "attribute": attr,
        "popularity": pop,
        "action": action,
    }


# ============================================================
# 二、sub_facilities 生成
# ============================================================

# 商场综合体子设施模板 (按商圈)
MALL_SUB_FACILITIES = {
    "人民广场商圈": [
        {
            "name": "卡通尼乐园", "type": "亲子乐园", "price_per_person": 80,
            "suggested_duration_minutes": 90,
            "highlight": "室内游乐区，3-8岁孩子放电2小时", "child_friendly": True,
            "tags": {"attribute": ["亲子友好", "室内恒温"], "popularity": ["小红书亲子Top3"], "action": ["有团购"]},
        },
        {
            "name": "CGV影城", "type": "私人影院", "price_per_person": 70,
            "suggested_duration_minutes": 120,
            "highlight": "recliner座椅，观影体验舒适", "child_friendly": True,
            "tags": {"attribute": ["亲子友好", "有包间"], "popularity": [], "action": ["有团购"]},
        },
        {
            "name": "奇境GOLF", "type": "聚会团建", "price_per_person": 120,
            "suggested_duration_minutes": 60,
            "highlight": "室内迷你高尔夫，朋友聚会新奇选择", "child_friendly": False,
            "tags": {"attribute": ["朋友聚会", "室内恒温"], "popularity": [], "action": []},
        },
    ],
    "前滩太古里周边": [
        {
            "name": "meland亲子乐园", "type": "亲子乐园", "price_per_person": 150,
            "suggested_duration_minutes": 120,
            "highlight": "高端亲子乐园，AI互动+角色扮演区，孩子玩到不想走", "child_friendly": True,
            "tags": {"attribute": ["亲子友好", "室内恒温"], "popularity": ["遛娃天花板"], "action": ["需预约", "有亲子票"]},
        },
        {
            "name": "Patagonia攀岩馆", "type": "聚会团建", "price_per_person": 180,
            "suggested_duration_minutes": 120,
            "highlight": "室内专业攀岩馆，含抱石和难度区", "child_friendly": True,
            "tags": {"attribute": ["中等互动", "室内恒温"], "popularity": ["小红书攀岩热门"], "action": ["需预约", "有团购"]},
        },
        {
            "name": "前滩时代影城", "type": "私人影院", "price_per_person": 100,
            "suggested_duration_minutes": 120,
            "highlight": "IMAX+杜比影厅，观影体验顶级", "child_friendly": True,
            "tags": {"attribute": ["有包间", "室内恒温"], "popularity": [], "action": ["有双人套餐"]},
        },
    ],
    "静安寺商圈": [
        {
            "name": "meland亲子乐园（静安店）", "type": "亲子乐园", "price_per_person": 120,
            "suggested_duration_minutes": 120,
            "highlight": "静安寺核心商圈内的亲子乐园，设施新、卫生好", "child_friendly": True,
            "tags": {"attribute": ["亲子友好", "室内恒温"], "popularity": ["大众点评4.8分"], "action": ["需预约", "有亲子票"]},
        },
        {
            "name": "Yoga Lab", "type": "健身瑜伽", "price_per_person": 150,
            "suggested_duration_minutes": 60,
            "highlight": "空中瑜伽+普拉提，白领午休首选", "child_friendly": False,
            "tags": {"attribute": ["低强度轻松", "室内恒温"], "popularity": ["小红书最火瑜伽馆"], "action": ["需预约"]},
        },
    ],
    "五角场商圈": [
        {
            "name": "汤姆熊欢乐世界", "type": "聚会团建", "price_per_person": 60,
            "suggested_duration_minutes": 60,
            "highlight": "经典电玩城，抓娃娃机和赛车，朋友PK好去处", "child_friendly": True,
            "tags": {"attribute": ["朋友聚会", "中等互动"], "popularity": ["五角场最火电玩"], "action": ["有团购"]},
        },
        {
            "name": "猫空·撸猫咖啡馆", "type": "聚会团建", "price_per_person": 68,
            "suggested_duration_minutes": 60,
            "highlight": "20+只品种猫，饮品+撸猫一站式体验", "child_friendly": True,
            "tags": {"attribute": ["安静治愈", "亲子友好"], "popularity": ["撸猫圣地"], "action": ["需预约"]},
        },
    ],
}

# 博物馆/科技馆子设施
MUSEUM_SUB_FACILITIES = {
    "自然博物馆": [
        {
            "name": "4D影院", "type": "私人影院", "price_per_person": 30,
            "suggested_duration_minutes": 25,
            "highlight": "恐龙主题4D短片，身临其境", "child_friendly": True,
            "tags": {"attribute": ["亲子友好", "室内恒温"], "popularity": [], "action": ["现场购票即可"]},
        },
        {
            "name": "探索中心互动区", "type": "亲子乐园", "price_per_person": 20,
            "suggested_duration_minutes": 40,
            "highlight": "化石挖掘体验+标本制作，动手学科学", "child_friendly": True,
            "tags": {"attribute": ["亲子友好", "中等互动"], "popularity": ["孩子玩到不想走"], "action": ["需预约"]},
        },
    ],
    "电影博物馆": [
        {
            "name": "4D影院", "type": "私人影院", "price_per_person": 30,
            "suggested_duration_minutes": 30,
            "highlight": "经典电影4D重现，沉浸感强", "child_friendly": True,
            "tags": {"attribute": ["亲子友好", "室内恒温"], "popularity": [], "action": ["现场购票即可"]},
        },
    ],
    "科技馆": [
        {
            "name": "球幕影院", "type": "私人影院", "price_per_person": 30,
            "suggested_duration_minutes": 30,
            "highlight": "IMAX球幕，科普短片视觉震撼", "child_friendly": True,
            "tags": {"attribute": ["亲子友好", "室内恒温"], "popularity": ["上海最大球幕"], "action": ["现场购票即可"]},
        },
    ],
}

# 电影院 - 可按影厅类型拆
CINEMA_SUB_FACILITIES = [
    {
        "name": "VIP情侣厅", "type": "私人影院", "price_per_person": 120,
        "suggested_duration_minutes": 120,
        "highlight": "双人沙发座，私密观影体验", "child_friendly": False,
        "tags": {"attribute": ["情侣约会", "有包间"], "popularity": [], "action": ["有双人套餐"]},
    },
]

# 休闲娱乐(KTV/密室/剧本杀) — 按房型
KTV_SUB_FACILITIES = [
    {
        "name": "小包（2-4人）", "type": "聚会团建", "price_per_person": 80,
        "suggested_duration_minutes": 120,
        "highlight": "适合2-4人嗨唱，音效专业", "child_friendly": False,
        "tags": {"attribute": ["朋友聚会"], "popularity": [], "action": ["有团购"]},
    },
    {
        "name": "中包（4-8人）", "type": "聚会团建", "price_per_person": 100,
        "suggested_duration_minutes": 180,
        "highlight": "适合4-8人聚会，有独立舞台", "child_friendly": False,
        "tags": {"attribute": ["朋友聚会", "团建首选"], "popularity": [], "action": ["有团购"]},
    },
    {
        "name": "大包（8-15人）", "type": "聚会团建", "price_per_person": 90,
        "suggested_duration_minutes": 180,
        "highlight": "超大包间，适合团建和生日趴", "child_friendly": False,
        "tags": {"attribute": ["团建首选"], "popularity": [], "action": ["有团购"]},
    },
]

MIJI_SUB_FACILITIES = [
    {
        "name": "机械解谜主题《星际迷航》", "type": "聚会团建", "price_per_person": 150,
        "suggested_duration_minutes": 90,
        "highlight": "科幻主题，机械解谜+互动装置，2-6人最佳", "child_friendly": True,
        "tags": {"attribute": ["中等互动", "室内恒温"], "popularity": ["小红书好评如潮"], "action": ["需预约"]},
    },
    {
        "name": "沉浸剧情《午夜钟声》", "type": "聚会团建", "price_per_person": 168,
        "suggested_duration_minutes": 120,
        "highlight": "悬疑推理剧情，需团队协作，4-8人", "child_friendly": False,
        "tags": {"attribute": ["中等互动", "室内恒温"], "popularity": ["新天地密室Top3"], "action": ["需预约"]},
    },
]

JB_SHA_SUB_FACILITIES = [
    {
        "name": "欢乐本《恋爱脑大作战》（4-6人）", "type": "聚会团建", "price_per_person": 158,
        "suggested_duration_minutes": 150,
        "highlight": "轻松搞笑，适合新手和朋友聚会", "child_friendly": False,
        "tags": {"attribute": ["朋友聚会"], "popularity": [], "action": ["需预约"]},
    },
    {
        "name": "硬核推理《沉默的真相》（6-8人）", "type": "聚会团建", "price_per_person": 198,
        "suggested_duration_minutes": 180,
        "highlight": "烧脑推理，多结局，老玩家必玩", "child_friendly": False,
        "tags": {"attribute": ["中等互动", "室内恒温"], "popularity": ["剧本杀圈口碑神作"], "action": ["需预约", "周末需提前3天"]},
    },
    {
        "name": "换装沉浸《长安十二时辰》（8-12人）", "type": "聚会团建", "price_per_person": 280,
        "suggested_duration_minutes": 240,
        "highlight": "古风换装+实景沉浸，NPC互动，团建首选", "child_friendly": False,
        "tags": {"attribute": ["团建首选", "室内恒温"], "popularity": ["出片率最高"], "action": ["必须预约", "周末需提前3天"]},
    },
]

# 手作体验 — 拆不同工种
HANDICRAFT_SUB_FACILITIES = {
    "静安寺手作工坊": [
        {
            "name": "陶艺拉坯体验", "type": "手作体验", "price_per_person": 158,
            "suggested_duration_minutes": 90,
            "highlight": "从揉泥到拉坯，老师一对一指导，作品可带走", "child_friendly": True,
            "tags": {"attribute": ["亲子友好", "安静治愈"], "popularity": [], "action": ["需预约"]},
        },
        {
            "name": "木工筷子制作", "type": "手作体验", "price_per_person": 128,
            "suggested_duration_minutes": 60,
            "highlight": "亲手打造一双木筷，体验传统木工技艺", "child_friendly": True,
            "tags": {"attribute": ["亲子友好", "安静治愈"], "popularity": [], "action": ["需预约"]},
        },
        {
            "name": "皮具钥匙扣DIY", "type": "手作体验", "price_per_person": 88,
            "suggested_duration_minutes": 45,
            "highlight": "入门皮具体验，选皮、打孔、缝线，成品实用美观", "child_friendly": True,
            "tags": {"attribute": ["亲子友好", "低强度轻松"], "popularity": [], "action": ["需预约"]},
        },
    ],
    "芮欧百货手工坊": [
        {
            "name": "银饰戒指DIY", "type": "手作体验", "price_per_person": 380,
            "suggested_duration_minutes": 120,
            "highlight": "从银料到成品戒指，全程指导，适合情侣", "child_friendly": False,
            "tags": {"attribute": ["情侣约会", "禅意雅致"], "popularity": ["小红书最火银饰DIY"], "action": ["必须预约", "周末需提前3天"]},
        },
        {
            "name": "皮具手包定制", "type": "手作体验", "price_per_person": 580,
            "suggested_duration_minutes": 180,
            "highlight": "意大利植鞣皮，手工缝制专属手包", "child_friendly": False,
            "tags": {"attribute": ["情侣约会", "禅意雅致"], "popularity": ["品质感十足"], "action": ["必须预约"]},
        },
    ],
}

# SPA — 拆不同服务区
SPA_SUB_FACILITIES = {
    "书屿SPA": [
        {
            "name": "精油全身按摩（60分钟）", "type": "洗浴汗蒸", "price_per_person": 298,
            "suggested_duration_minutes": 60,
            "highlight": "选用泰国进口精油，深度放松肌肉", "child_friendly": False,
            "tags": {"attribute": ["安静治愈"], "popularity": [], "action": ["需预约", "有团购"]},
        },
        {
            "name": "书店阅读+头疗（90分钟）", "type": "其他", "price_per_person": 198,
            "suggested_duration_minutes": 90,
            "highlight": "边看书边做头部按摩，白领减压神器", "child_friendly": False,
            "tags": {"attribute": ["安静治愈", "低强度轻松"], "popularity": ["五角场白领最爱"], "action": ["需预约"]},
        },
    ],
    "云水间": [
        {
            "name": "颂钵疗愈（90分钟）", "type": "其他", "price_per_person": 498,
            "suggested_duration_minutes": 90,
            "highlight": "7个颂钵对应7个脉轮，深度冥想体验", "child_friendly": False,
            "tags": {"attribute": ["禅意雅致", "安静治愈"], "popularity": ["上海独有"], "action": ["必须预约"]},
        },
        {
            "name": "热石按摩（75分钟）", "type": "洗浴汗蒸", "price_per_person": 398,
            "suggested_duration_minutes": 75,
            "highlight": "火山热石按摩，驱寒暖身，适合体寒人群", "child_friendly": False,
            "tags": {"attribute": ["安静治愈"], "popularity": [], "action": ["需预约", "有团购"]},
        },
    ],
    "阅光": [
        {
            "name": "头部按摩+饮品（60分钟）", "type": "其他", "price_per_person": 68,
            "suggested_duration_minutes": 60,
            "highlight": "头部SPA+咖啡/茶饮，文艺青年最爱", "child_friendly": True,
            "tags": {"attribute": ["安静治愈", "低强度轻松"], "popularity": ["性价比超高"], "action": []},
        },
    ],
}


def generate_sub_facilities(poi: dict) -> list:
    """根据 POI 类型生成子设施。"""
    poi_type = poi.get("type", "")
    poi_id = poi.get("id", "")
    poi_name = poi.get("name", "")
    district = poi.get("location", {}).get("district", "")
    poi_cat = poi.get("poi_category", "")

    # 商场综合体 → 一定拆
    if poi_type == "mall":
        return copy.deepcopy(MALL_SUB_FACILITIES.get(district, MALL_SUB_FACILITIES.get("人民广场商圈", [])))

    # 博物馆/科技馆
    if poi_type == "museum":
        if "自然博物馆" in poi_name:
            return copy.deepcopy(MUSEUM_SUB_FACILITIES.get("自然博物馆", []))
        if "电影" in poi_name:
            return copy.deepcopy(MUSEUM_SUB_FACILITIES.get("电影博物馆", []))
        if "科技馆" in poi_name:
            return copy.deepcopy(MUSEUM_SUB_FACILITIES.get("科技馆", []))
        if "儿童" in poi_name:
            return []  # 儿童博物馆不拆
        return []

    # 商业街/公园/户外 → 不拆
    if poi_type in ("commercial_street", "park"):
        return []

    # 展览/沉浸式 → 不拆
    if poi_type == "exhibition":
        return []

    # 电影院 → 可按影厅拆
    if poi_type == "cinema":
        return copy.deepcopy(CINEMA_SUB_FACILITIES)

    # KTV → 按房型拆
    if poi_type == "ktv":
        return copy.deepcopy(KTV_SUB_FACILITIES)

    # 密室逃脱 → 拆不同主题
    if poi_type == "桌游":
        return copy.deepcopy(MIJI_SUB_FACILITIES)

    # 剧本杀 → 拆不同本
    if poi_type == "剧本杀":
        return copy.deepcopy(JB_SHA_SUB_FACILITIES)

    # 手作体验 → 拆不同工种
    if poi_type == "handicraft":
        if "芮欧" in poi_name:
            return copy.deepcopy(HANDICRAFT_SUB_FACILITIES.get("芮欧百货手工坊", []))
        if "静安寺" in poi_name:
            return copy.deepcopy(HANDICRAFT_SUB_FACILITIES.get("静安寺手作工坊", []))
        return []  # 市集不拆

    # SPA → 拆不同服务
    if poi_type == "spa":
        if "书屿" in poi_name:
            return copy.deepcopy(SPA_SUB_FACILITIES.get("书屿SPA", []))
        if "云水间" in poi_name:
            return copy.deepcopy(SPA_SUB_FACILITIES.get("云水间", []))
        if "阅光" in poi_name:
            return copy.deepcopy(SPA_SUB_FACILITIES.get("阅光", []))
        return []

    return []


# ============================================================
# 三、coupons 生成
# ============================================================

def generate_coupons(poi: dict, is_restaurant: bool = False) -> list:
    """为 POI 生成 1-3 条优惠券。人均=0 且无收费项目则不生成。"""
    price = poi.get("price_per_person", 0)
    poi_type = poi.get("type", "")
    poi_name = poi.get("name", "")
    poi_id = poi.get("id", "")

    if price == 0:
        # 检查是否有收费子设施
        subs = poi.get("sub_facilities", [])
        if not subs:
            return []

    coupons = []

    if is_restaurant:
        # 餐厅推套餐
        if poi_type in ("hotpot", "bbq", "exotic", "cantonese"):
            # 双人/4人套餐
            original_4 = int(price * 4 * 0.95)
            coupon_4 = int(original_4 * 0.72)
            coupons.append({
                "title": f"4人聚会套餐",
                "platform": "meituan",
                "original_price": original_4,
                "coupon_price": coupon_4,
                "description": f"含招牌菜+饮品+主食，适合4人聚餐",
                "valid_until": VALID_UNTIL_DEFAULT,
            })
            if price <= 200:
                original_2 = int(price * 2 * 0.95)
                coupon_2 = int(original_2 * 0.75)
                coupons.append({
                    "title": "双人套餐",
                    "platform": "dianping",
                    "original_price": original_2,
                    "coupon_price": coupon_2,
                    "description": "含2份招牌菜+饮品",
                    "valid_until": VALID_UNTIL_DEFAULT,
                })
        elif poi_type == "japanese":
            original = int(price * 2 * 0.9)
            coupon = int(original * 0.7)
            coupons.append({
                "title": "双人Omakase体验",
                "platform": "dianping",
                "original_price": original,
                "coupon_price": coupon,
                "description": "含前菜+刺身+寿司+甜品",
                "valid_until": VALID_UNTIL_JULY,
            })
        elif poi_type == "western":
            if price >= 800:
                coupons.append({
                    "title": "双人品鉴晚餐",
                    "platform": "dianping",
                    "original_price": int(price * 2 * 0.9),
                    "coupon_price": int(price * 2 * 0.65),
                    "description": "含前菜+主菜+甜品+配酒",
                    "valid_until": VALID_UNTIL_JULY,
                })
            else:
                coupons.append({
                    "title": "双人法式晚餐",
                    "platform": "meituan",
                    "original_price": int(price * 2 * 0.9),
                    "coupon_price": int(price * 2 * 0.72),
                    "description": "含主菜+甜品+饮品",
                    "valid_until": VALID_UNTIL_DEFAULT,
                })
        elif poi_type == "cafe_dessert":
            coupons.append({
                "title": f"双人下午茶套餐",
                "platform": "meituan",
                "original_price": int(price * 2 * 1.1),
                "coupon_price": int(price * 2 * 0.68),
                "description": "含2杯饮品+2份甜品",
                "valid_until": VALID_UNTIL_DEFAULT,
            })
        elif poi_type == "light_meal":
            coupons.append({
                "title": "双人轻食套餐",
                "platform": "meituan",
                "original_price": int(price * 2 * 1.1),
                "coupon_price": int(price * 2 * 0.72),
                "description": "含2份主菜+2杯饮品",
                "valid_until": VALID_UNTIL_DEFAULT,
            })
        elif poi_type == "street_food":
            coupons.append({
                "title": "双人夜宵套餐",
                "platform": "meituan",
                "original_price": int(price * 2 * 1.1),
                "coupon_price": int(price * 2 * 0.7),
                "description": "含招牌菜+饮品+小食",
                "valid_until": VALID_UNTIL_DEFAULT,
            })
    else:
        # 活动 POI 推亲子票/双人票
        if poi_type == "mall":
            coupons.append({
                "title": "停车券满200减10",
                "platform": "self",
                "original_price": 10,
                "coupon_price": 0,
                "description": "当日消费满200元，停车立减10元",
                "valid_until": VALID_UNTIL_SEPTEMBER,
            })
        elif poi_type == "museum":
            original = int(price * 2 * 1.1)
            coupon = int(original * 0.7)
            coupons.append({
                "title": "双人参观票",
                "platform": "meituan",
                "original_price": original,
                "coupon_price": coupon,
                "description": "含2张门票，比单买优惠",
                "valid_until": VALID_UNTIL_AUGUST,
            })
            if poi.get("child_friendly"):
                coupons.append({
                    "title": "1大1小亲子票",
                    "platform": "dianping",
                    "original_price": int(price * 1.6),
                    "coupon_price": int(price * 1.1),
                    "description": "含1成人+1儿童门票",
                    "valid_until": VALID_UNTIL_AUGUST,
                })
        elif poi_type == "exhibition":
            if price > 0:
                coupons.append({
                    "title": "双人观展票",
                    "platform": "meituan",
                    "original_price": int(price * 2 * 1.1),
                    "coupon_price": int(price * 2 * 0.75),
                    "description": "含2张门票",
                    "valid_until": VALID_UNTIL_DEFAULT,
                })
        elif poi_type == "cinema":
            coupons.append({
                "title": "双人观影套餐",
                "platform": "dianping",
                "original_price": int(price * 2 + 40),
                "coupon_price": int(price * 2 * 0.72),
                "description": "2张电影票+1份爆米花+2杯可乐",
                "valid_until": VALID_UNTIL_JULY,
            })
        elif poi_type == "ktv":
            coupons.append({
                "title": "4人欢唱套餐（含饮品）",
                "platform": "meituan",
                "original_price": int(price * 4 * 1.1),
                "coupon_price": int(price * 4 * 0.68),
                "description": "含4小时欢唱+饮品小食",
                "valid_until": VALID_UNTIL_DEFAULT,
            })
        elif poi_type == "桌游":
            coupons.append({
                "title": "4人密室逃脱套餐",
                "platform": "meituan",
                "original_price": int(price * 4),
                "coupon_price": int(price * 4 * 0.75),
                "description": "4人组队享75折",
                "valid_until": VALID_UNTIL_DEFAULT,
            })
        elif poi_type == "剧本杀":
            coupons.append({
                "title": "6人剧本杀套餐",
                "platform": "meituan",
                "original_price": int(price * 6),
                "coupon_price": int(price * 6 * 0.72),
                "description": "6人同行享72折",
                "valid_until": VALID_UNTIL_DEFAULT,
            })
        elif poi_type == "spa":
            coupons.append({
                "title": "首次体验5折",
                "platform": "dianping",
                "original_price": price,
                "coupon_price": int(price * 0.5),
                "description": "新客首次体验基础项目享5折",
                "valid_until": VALID_UNTIL_DEFAULT,
            })
        elif poi_type in ("handicraft", "commercial_street", "park"):
            if price > 0:
                coupons.append({
                    "title": "双人体验套餐",
                    "platform": "meituan",
                    "original_price": int(price * 2),
                    "coupon_price": int(price * 2 * 0.75),
                    "description": "双人同行享优惠",
                    "valid_until": VALID_UNTIL_DEFAULT,
                })

    return coupons


# ============================================================
# 四、seasonal_events 生成
# ============================================================

def generate_seasonal_events(poi: dict) -> list:
    """为活动/展览/博物馆/商场类 POI 生成近期活动。公园/户外/SPA/餐厅不生成。"""
    poi_type = poi.get("type", "")
    poi_name = poi.get("name", "")
    poi_cat = poi.get("poi_category", "")

    # 不生成的类型
    if poi_type in ("park", "spa", "commercial_street"):
        return []

    events = []

    if poi_type == "mall":
        mall_events = {
            "来福士广场": [
                {"name": "夏日冰爽节", "date_range": "2026-06-15 ~ 2026-07-15",
                 "description": "全场餐饮满100减20，B1甜品买一送一", "price": "免费参与", "source": "商场官方公众号"},
            ],
            "新世界城": [
                {"name": "亲子嘉年华", "date_range": "2026-06-01 ~ 2026-09-01",
                 "description": "室内游乐场套票8折，亲子手工周末免费体验", "price": "免费参与", "source": "商场官方公众号"},
                {"name": "夏日积木大赛", "date_range": "2026-07-01 ~ 2026-08-31",
                 "description": "乐高积木拼搭比赛，每周冠军有奖", "price": "免费参与", "source": "乐高探索中心公众号"},
            ],
            "第一百货商业中心": [
                {"name": "老字号美食节", "date_range": "2026-06-10 ~ 2026-07-10",
                 "description": "汇聚上海老字号美食，品尝+文化展", "price": "免费入场", "source": "商场官网"},
            ],
            "世茂广场": [
                {"name": "M&M's夏日限定", "date_range": "2026-06-01 ~ 2026-08-31",
                 "description": "M&M's旗舰店夏日限定巧克力豆，限定配色礼盒上线", "price": "免费参观", "source": "M&M's旗舰店公众号"},
            ],
            "晶耀前滩": [
                {"name": "前滩夏日市集", "date_range": "2026-06-20 ~ 2026-08-20",
                 "description": "每周末户外创意市集+亲子互动区，歌手驻唱", "price": "免费入场", "source": "晶耀前滩公众号"},
            ],
        }
        for key, evts in mall_events.items():
            if key in poi_name:
                events.extend(evts)
        if not events:
            # generic mall event
            events.append({
                "name": "夏日狂欢季", "date_range": "2026-06-15 ~ 2026-08-15",
                "description": "全场折扣+亲子活动，周末有抽奖", "price": "免费参与", "source": "商场公众号",
            })

    elif poi_type == "museum":
        museum_events = {
            "上海自然博物馆": [
                {"name": "深海奇境特展", "date_range": "2026-05-01 ~ 2026-08-31",
                 "description": "深海生物标本+VR沉浸体验，8个互动装置", "price": "含在门票内", "source": "上海自然博物馆官网"},
                {"name": "恐龙星球·暑期特别展", "date_range": "2026-06-20 ~ 2026-09-20",
                 "description": "大型恐龙骨架+AI互动，还原侏罗纪世界", "price": "含在门票内", "source": "上海自然博物馆官网"},
            ],
            "上海电影博物馆": [
                {"name": "百年上海电影回顾展", "date_range": "2026-06-01 ~ 2026-09-30",
                 "description": "经典电影道具+海报展，含老电影放映", "price": "含在门票内", "source": "上海电影博物馆公众号"},
            ],
            "上海儿童博物馆": [
                {"name": "小小科学家暑期营", "date_range": "2026-07-01 ~ 2026-08-31",
                 "description": "每周六科学实验课，适合3-7岁", "price": "50元/次", "source": "儿童博物馆官网"},
            ],
            "上海科技馆特展厅": [
                {"name": "AI与未来特展", "date_range": "2026-06-15 ~ 2026-09-15",
                 "description": "AI机器人互动+VR未来城市体验", "price": "含在门票内", "source": "上海科技馆官网"},
            ],
        }
        for key, evts in museum_events.items():
            if key in poi_name:
                events.extend(evts)
        if not events:
            events.append({
                "name": "暑期特展", "date_range": "2026-06-15 ~ 2026-09-15",
                "description": "暑期限定互动展览", "price": "含在门票内", "source": "馆方公众号",
            })

    elif poi_type == "exhibition":
        exhib_events = {
            "世纪公园当代艺术馆": [
                {"name": "当代水墨双年展", "date_range": "2026-06-01 ~ 2026-08-31",
                 "description": "国内外当代水墨艺术家联展", "price": "含在门票内", "source": "艺术馆官网"},
            ],
            "世纪汇广场光影展": [
                {"name": "夏日花火·光影特展", "date_range": "2026-06-15 ~ 2026-09-15",
                 "description": "日式花火大会主题光影展，沉浸式烟火体验", "price": "68元/人", "source": "世纪汇广场公众号"},
            ],
        }
        for key, evts in exhib_events.items():
            if key in poi_name:
                events.extend(evts)
        if not events:
            events.append({
                "name": "夏季限定展", "date_range": "2026-06-15 ~ 2026-09-15",
                "description": "夏季限定主题展览", "price": "含在门票内", "source": "场馆公众号",
            })

    # 香港名都 (mall) 没有匹配的要单独处理
    if poi_name == "香港名都" and not events:
        events.append({
            "name": "港味美食季", "date_range": "2026-06-10 ~ 2026-07-10",
            "description": "香港特色美食摊位+茶餐厅文化展", "price": "免费入场", "source": "商场公众号",
        })
    if poi_name == "上海来福士广场" and not events:
        events.append({
            "name": "来福士夏日音乐节", "date_range": "2026-07-01 ~ 2026-08-31",
            "description": "每周末B1中庭Live音乐表演", "price": "免费参与", "source": "来福士公众号",
        })

    return events


# ============================================================
# 五、nearby_dining 生成（仅活动 POI）
# ============================================================

# 餐厅 POI 索引 (按 district)
RESTAURANT_INDEX = {}  # 延迟构建

def build_restaurant_index(restaurants: list):
    """按 district 索引餐厅。"""
    global RESTAURANT_INDEX
    RESTAURANT_INDEX = {}
    for r in restaurants:
        d = r.get("location", {}).get("district", "")
        if d not in RESTAURANT_INDEX:
            RESTAURANT_INDEX[d] = []
        RESTAURANT_INDEX[d].append(r)


def generate_nearby_dining(poi: dict) -> list:
    """为活动 POI 生成 2-3 条附近餐饮。优先匹配同 district 的 seed 餐厅。"""
    district = poi.get("location", {}).get("district", "")
    poi_name = poi.get("name", "")
    poi_type = poi.get("type", "")

    nearby = []

    # 优先匹配 seed 中的餐厅
    if district in RESTAURANT_INDEX:
        candidates = RESTAURANT_INDEX[district]
        for r in candidates[:3]:
            nearby.append({
                "name": r["name"],
                "cuisine": r.get("cuisine_type", ""),
                "price_per_person": r.get("price_per_person", 0),
                "walking_minutes": random.choice([5, 8, 10]),
                "highlight": r.get("description", "")[:30] + "…" if len(r.get("description", "")) > 30 else r.get("description", ""),
            })

    # 不够 3 条则补充虚构餐饮
    FICTIONAL_DINING = {
        "人民广场商圈": [
            {"name": "沈大成", "cuisine": "本帮点心", "price_per_person": 45, "highlight": "百年老字号，条头糕和双酿团必买"},
            {"name": "佳家汤包", "cuisine": "上海小笼", "price_per_person": 50, "highlight": "黄河路排队王，蟹粉小笼鲜掉眉毛"},
        ],
        "静安寺商圈": [
            {"name": "南翔馒头店（静安店）", "cuisine": "上海小笼", "price_per_person": 80, "highlight": "百年老店，鲜肉小笼汤汁饱满"},
            {"name": "CHARLIE'S 粉红汉堡", "cuisine": "美式汉堡", "price_per_person": 65, "highlight": "网红粉红汉堡，奶昔也很赞"},
        ],
        "前滩太古里周边": [
            {"name": "Shake Shack（前滩太古里）", "cuisine": "美式汉堡", "price_per_person": 80, "highlight": "纽约网红汉堡，户外座位看江景"},
            {"name": "孔雀川菜", "cuisine": "川菜", "price_per_person": 130, "highlight": "Tiffany蓝装修川菜馆，颜值与口味并存"},
        ],
        "五角场商圈": [
            {"name": "大学路夜市", "cuisine": "夜市小吃", "price_per_person": 50, "highlight": "大学路周末夜市，各类小吃应有尽有"},
            {"name": "肥汁米线", "cuisine": "云南米线", "price_per_person": 35, "highlight": "酸辣开胃，大学生最爱"},
        ],
        "武康路衡复街区": [
            {"name": "% Arabica（武康路）", "cuisine": "精品咖啡", "price_per_person": 45, "highlight": "京都网红咖啡，武康路拍照打卡点"},
            {"name": "RAC Bar", "cuisine": "法式简餐", "price_per_person": 120, "highlight": "武康路网红brunch，可丽饼一绝"},
        ],
        "新天地周边": [
            {"name": "Shake Shack（新天地）", "cuisine": "美式汉堡", "price_per_person": 80, "highlight": "石库门里的纽约汉堡，中西碰撞"},
            {"name": "GREEN & SAFE", "cuisine": "有机轻食", "price_per_person": 150, "highlight": "农场到餐桌，有机食材健康美味"},
        ],
        "世纪公园周边": [
            {"name": "一坐一忘丽江主题餐厅", "cuisine": "云南菜", "price_per_person": 120, "highlight": "丽江风情，黑松露炒饭很香"},
            {"name": "O'mills Bakery", "cuisine": "面包甜品", "price_per_person": 65, "highlight": "手工酸面包和肉桂卷，brunch好去处"},
        ],
    }

    while len(nearby) < 2:
        fictional_list = FICTIONAL_DINING.get(district, [])
        for f in fictional_list:
            if not any(n["name"] == f["name"] for n in nearby):
                f["walking_minutes"] = random.choice([5, 8, 10])
                nearby.append(f)
                if len(nearby) >= 2:
                    break
        if len(nearby) < 2:
            break

    return nearby[:3]


# ============================================================
# 六、related_activity_poi（仅餐厅 POI）
# ============================================================

# 跨区就近映射（当餐厅所在区没有活动时使用）
CROSS_DISTRICT_ACTIVITY_MAP = {
    "北外滩滨水区": "人民广场商圈",      # 北外滩 → 人民广场（最近）
    "陆家嘴滨江": "世纪公园周边",        # 陆家嘴 → 世纪公园
    "虹桥天地周边": "静安寺商圈",         # 虹桥 → 静安寺
}


def generate_related_activity(restaurant: dict, activities: list) -> str:
    """为餐厅关联附近的活动 POI（同 district 优先，否则就近映射）。"""
    r_district = restaurant.get("location", {}).get("district", "")
    r_name = restaurant.get("name", "")

    # 同 district 活动
    same_district = [a for a in activities if a.get("location", {}).get("district") == r_district]
    if same_district:
        act = same_district[0]
        walking = random.choice([5, 8, 10])
        return f"{act['id']} {act['name']}（步行{walking}分钟）"

    # 跨区就近映射
    mapped_district = CROSS_DISTRICT_ACTIVITY_MAP.get(r_district, "")
    if mapped_district:
        mapped_acts = [a for a in activities if a.get("location", {}).get("district") == mapped_district]
        if mapped_acts:
            act = random.choice(mapped_acts)
            return f"{act['id']} {act['name']}（约2km，地铁可达）"

    # 最终兜底
    if activities:
        act = activities[0]
        return f"{act['id']} {act['name']}"

    return ""


# ============================================================
# 主流程
# ============================================================

def process_activities(activities: list, restaurants: list) -> list:
    """处理所有活动 POI，补充扩展字段。"""
    build_restaurant_index(restaurants)
    result = []

    for act in activities:
        poi = copy.deepcopy(act)

        # 1. 生成三维 tags
        poi["tags"] = build_tags_3d(act, is_restaurant=False)

        # 2. 生成 sub_facilities
        poi["sub_facilities"] = generate_sub_facilities(act)

        # 3. 生成 coupons
        poi["coupons"] = generate_coupons(act, is_restaurant=False)

        # 4. 生成 seasonal_events
        poi["seasonal_events"] = generate_seasonal_events(act)

        # 5. 生成 nearby_dining
        poi["nearby_dining"] = generate_nearby_dining(act)

        # 删除旧字段
        for old_field in ["atmosphere_tags", "risk_tags", "recommendation_reason_seed"]:
            poi.pop(old_field, None)

        result.append(poi)

    return result


def process_restaurants(restaurants: list, activities: list) -> list:
    """处理所有餐厅 POI，补充扩展字段。"""
    result = []

    for rest in restaurants:
        poi = copy.deepcopy(rest)

        # 1. 生成三维 tags
        poi["tags"] = build_tags_3d(rest, is_restaurant=True)

        # 2. 生成 coupons（无 sub_facilities、seasonal_events、nearby_dining）
        poi["coupons"] = generate_coupons(rest, is_restaurant=True)

        # 3. 关联附近活动
        poi["related_activity_poi"] = generate_related_activity(rest, activities)

        # 删除旧字段
        for old_field in ["atmosphere_tags", "risk_tags", "recommendation_reason_seed"]:
            poi.pop(old_field, None)

        result.append(poi)

    return result


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)

    seed_path = os.path.join(project_dir, "data", "poi_seed.yaml")
    output_path = os.path.join(project_dir, "data", "poi-knowledge-base-shanghai.yaml")

    # 读取 seed
    with open(seed_path, "r", encoding="utf-8") as f:
        seed = yaml.safe_load(f)

    activities = seed.get("activities", [])
    restaurants = seed.get("restaurants", [])

    print(f"读取 seed: {len(activities)} activities + {len(restaurants)} restaurants")

    # 处理
    processed_activities = process_activities(activities, restaurants)
    processed_restaurants = process_restaurants(restaurants, activities)

    # 构建输出
    output = copy.deepcopy(seed)
    output["activities"] = processed_activities
    output["restaurants"] = processed_restaurants
    output["metadata"]["generator"] = "scripts/generate_poi_knowledge_base.py"
    output["metadata"]["generated_at"] = CURRENT_DATE
    output["description"] = "上海本地生活 POI 知识库（含三维标签/子设施/优惠券/近期活动/附近餐饮）"

    # 写入
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(output, f, allow_unicode=True, default_flow_style=False, sort_keys=False, width=120)

    print(f"输出: {output_path}")
    print(f"  activities: {len(processed_activities)}")
    print(f"  restaurants: {len(processed_restaurants)}")

    # 验证
    for i, act in enumerate(processed_activities):
        assert "tags" in act and isinstance(act["tags"], dict), f"{act['id']}: tags missing or wrong type"
        assert "attribute" in act["tags"], f"{act['id']}: tags.attribute missing"
        assert "popularity" in act["tags"], f"{act['id']}: tags.popularity missing"
        assert "action" in act["tags"], f"{act['id']}: tags.action missing"
        assert "coupons" in act, f"{act['id']}: coupons missing"
        assert "nearby_dining" in act, f"{act['id']}: nearby_dining missing"
        assert "atmosphere_tags" not in act, f"{act['id']}: atmosphere_tags not removed"
        assert "risk_tags" not in act, f"{act['id']}: risk_tags not removed"
        assert "recommendation_reason_seed" not in act, f"{act['id']}: recommendation_reason_seed not removed"

    for i, rest in enumerate(processed_restaurants):
        assert "tags" in rest and isinstance(rest["tags"], dict), f"{rest['id']}: tags missing or wrong type"
        assert "coupons" in rest, f"{rest['id']}: coupons missing"
        assert "related_activity_poi" in rest, f"{rest['id']}: related_activity_poi missing"
        assert "atmosphere_tags" not in rest, f"{rest['id']}: atmosphere_tags not removed"
        assert "risk_tags" not in rest, f"{rest['id']}: risk_tags not removed"
        assert "recommendation_reason_seed" not in rest, f"{rest['id']}: recommendation_reason_seed not removed"

    print("\n✅ 验证通过！所有 POI 字段完整，旧字段已清理。")


if __name__ == "__main__":
    main()
