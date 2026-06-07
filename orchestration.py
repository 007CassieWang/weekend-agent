"""
Orchestration 状态机 — Round 1 泛方案卡片 + Round 2 选择锁定 + 跳步 + 防死循环

流程位置：小猜问（Round 0 Q2）→ 泛方案卡片（Round 1）→ 用户选择（Round 2）→ 正式方案生成（Round 3）

职责：
- Round 1: 根据用户已收集的槽位（group_type 等）生成 3 张泛方案卡片
- Round 2: 用户选择卡片后锁定约束，合并卡片隐含约束到槽位
- Round X: 必填槽位缺失时插入引导
- 跳步逻辑: 用户信息丰富时跳过部分 Round
- 防死循环: max_rounds / max_slot_guidance / 重复检测
"""

from __future__ import annotations

import logging
import re
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("weekend_agent.orchestration")


# ==================== 常量 ====================

BENCHMARK = {
    "max_rounds": 8,
    "max_slot_guidance": 3,
    "max_same_question": 2,
    "timeout_per_round": 30,
    "fallback_threshold": 3,
}

GROUP_TYPE = ["家庭出行", "朋友聚会", "情侣约会", "独自一人"]
TIME_SLOT = ["今天", "明天", "本周末", "下周末", "自定义"]
MOBILITY = ["自驾", "打车", "公共交通", "无偏好"]

SLOT_DEFAULTS = {
    "child_age": 5,
    "max_duration": 4,
    "budget": "中等",
}

REQUIRED_SLOTS = {
    "家庭出行": ["group_type", "time_slot", "mobility", "child_age"],
    "朋友聚会": ["group_type", "time_slot", "mobility"],
    "情侣约会": ["group_type", "time_slot", "mobility"],
    "独自一人": ["group_type", "time_slot", "mobility"],
}


# ==================== 状态机 ====================

class State(Enum):
    INIT = "init"
    SLOT_COLLECTING = "slot_collecting"
    GUESS_QUESTIONS = "guess_questions"
    TEMPLATE_CARDS = "template_cards"
    PLAN_SEARCHING = "plan_searching"
    PLAN_SHOWN = "plan_shown"
    RECEIPT_GENERATED = "receipt_generated"
    COMPLETED = "completed"


TRANSITIONS = {
    State.INIT: {
        "user_click": State.SLOT_COLLECTING,
    },
    State.SLOT_COLLECTING: {
        "slots_filled": State.GUESS_QUESTIONS,
        "can_skip": State.TEMPLATE_CARDS,
        "missing_slots": State.SLOT_COLLECTING,  # Round X
    },
    State.GUESS_QUESTIONS: {
        "user_select": State.TEMPLATE_CARDS,
        "can_skip": State.PLAN_SEARCHING,
    },
    State.TEMPLATE_CARDS: {
        "user_select": State.PLAN_SEARCHING,
    },
    State.PLAN_SEARCHING: {
        "search_complete": State.PLAN_SHOWN,
    },
    State.PLAN_SHOWN: {
        "user_confirm": State.RECEIPT_GENERATED,
        "user_modify": State.SLOT_COLLECTING,  # 回溯
    },
    State.RECEIPT_GENERATED: {
        "complete": State.COMPLETED,
    },
}


# ==================== SessionState ====================

@dataclass
class SessionState:
    """会话状态，贯穿多轮交互"""
    session_id: str
    current_round: int = 0
    current_state: State = State.INIT

    # 槽位信息
    slots: Dict[str, Any] = field(default_factory=dict)
    locked_constraints: Dict[str, Any] = field(default_factory=dict)

    # 用户选择历史
    user_selections: List[Dict[str, Any]] = field(default_factory=list)

    # Benchmark 计数
    slot_guidance_count: int = 0
    repeat_question_count: int = 0
    no_response_count: int = 0

    # 方案数据
    candidate_plans: Optional[List[Dict[str, Any]]] = None
    selected_plan: Optional[Dict[str, Any]] = None

    # 最后提问（用于重复检测）
    last_question: Optional[str] = None
    current_question: Optional[str] = None

    def transition(self, event: str) -> Optional[State]:
        """执行状态转移，返回新状态。若转移非法则返回 None。"""
        allowed = TRANSITIONS.get(self.current_state, {})
        new_state = allowed.get(event)
        if new_state:
            self.current_state = new_state
            self.current_round += 1
        return new_state

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "current_round": self.current_round,
            "current_state": self.current_state.value,
            "slots": self.slots,
            "locked_constraints": self.locked_constraints,
            "slot_guidance_count": self.slot_guidance_count,
        }


# ==================== Round 1: 泛方案卡片 ====================

# 各组场景的泛方案卡片模板
TEMPLATE_CARD_DEFS: Dict[str, List[Dict[str, Any]]] = {
    "家庭出行": [
        {
            "card_id": "card_family_1",
            "title": "轻松省心 · 室内一站式",
            "description": "孩子玩得住，大人也不累，全程一个地方搞定",
            "tags": ["室内", "短车程", "低强度", "一站式"],
            "implied_constraints": {
                "intent_mode": "relax",
                "indoor_outdoor": "indoor",
                "activity_intensity": "low",
                "travel_radius": "short",
            },
            "example_content": "商场亲子乐园 / 科技馆儿童区 / 室内游乐馆 + 顺路吃饭",
        },
        {
            "card_id": "card_family_2",
            "title": "放电互动 · 孩子能参与",
            "description": "不是纯逛，有动手、有互动、孩子能沉浸玩",
            "tags": ["互动", "参与感", "沉浸"],
            "implied_constraints": {
                "intent_mode": "interact",
                "activity_intensity": "medium",
                "theme": "interactive",
            },
            "example_content": "儿童科学乐园 / 手作体验馆 / 互动主题展",
        },
        {
            "card_id": "card_family_3",
            "title": "有点特别 · 不只是遛娃",
            "description": "有新鲜感，能留下记忆点",
            "tags": ["新鲜", "小众", "记忆点"],
            "implied_constraints": {
                "intent_mode": "novelty",
                "feature": "special",
            },
            "example_content": "快闪展 / 小众主题馆 / 特色体验空间",
        },
    ],
    "朋友聚会": [
        {
            "card_id": "card_friends_1",
            "title": "边走边聊 · 轻松漫步",
            "description": "不用刻意安排，走走停停边逛边聊",
            "tags": ["轻松", "灵活", "低消费"],
            "implied_constraints": {
                "intent_mode": "relax",
                "activity_intensity": "low",
                "structure": "loose",
            },
            "example_content": "Citywalk路线 / 创意园区 / 滨江步道 + 路边小店",
        },
        {
            "card_id": "card_friends_2",
            "title": "共同体验 · 一起玩点什么",
            "description": "有参与感的活动，大家一起动手或竞技",
            "tags": ["互动", "参与感", "团队感"],
            "implied_constraints": {
                "intent_mode": "interact",
                "activity_intensity": "medium",
                "theme": "social",
            },
            "example_content": "密室逃脱 / 剧本杀 / 桌游馆 / 手工坊 / 保龄球",
        },
        {
            "card_id": "card_friends_3",
            "title": "找个地方坐坐 · 吃喝为主",
            "description": "不用折腾，找个舒服的地方好好吃一顿聊聊天",
            "tags": ["美食", "放松", "氛围"],
            "implied_constraints": {
                "intent_mode": "dining",
                "activity_intensity": "low",
                "theme": "food_social",
            },
            "example_content": "特色餐厅 / 露台餐吧 / 精酿酒吧 + 甜品店续摊",
        },
    ],
    "情侣约会": [
        {
            "card_id": "card_couple_1",
            "title": "浪漫氛围 · 仪式感约会",
            "description": "精心安排，有记忆点的约会体验",
            "tags": ["浪漫", "仪式感", "出片"],
            "implied_constraints": {
                "intent_mode": "romantic",
                "atmosphere": "romantic",
                "photo_spot": True,
            },
            "example_content": "景观餐厅 / 烛光晚餐 / 江景露台 + 夜间漫步",
        },
        {
            "card_id": "card_couple_2",
            "title": "互动体验 · 一起做点什么",
            "description": "共同参与的活动，创造共同的回忆",
            "tags": ["互动", "合作", "体验"],
            "implied_constraints": {
                "intent_mode": "interact",
                "activity_intensity": "medium",
                "theme": "couple_activity",
            },
            "example_content": "双人手作 / 陶艺体验 / 烘焙课 / 双人油画",
        },
        {
            "card_id": "card_couple_3",
            "title": "轻松漫步 · 悠闲相伴",
            "description": "不用赶行程，享受二人时光的慢节奏",
            "tags": ["轻松", "漫步", "随心"],
            "implied_constraints": {
                "intent_mode": "relax",
                "activity_intensity": "low",
                "structure": "loose",
            },
            "example_content": "公园散步 / 咖啡馆探店 / 书店闲逛 + 街边小吃",
        },
    ],
    "独自一人": [
        {
            "card_id": "card_solo_1",
            "title": "放松充电 · 犒劳自己",
            "description": "安安静静享受属于自己的时间",
            "tags": ["放松", "治愈", "独处"],
            "implied_constraints": {
                "intent_mode": "relax",
                "activity_intensity": "low",
                "atmosphere": "quiet",
            },
            "example_content": "书店 + 咖啡馆 / SPA按摩 / 温泉泡汤 / 独立影院",
        },
        {
            "card_id": "card_solo_2",
            "title": "探索体验 · 发现新鲜事",
            "description": "一个人也能玩得很充实，发现城市的新角落",
            "tags": ["探索", "新鲜", "充实"],
            "implied_constraints": {
                "intent_mode": "explore",
                "activity_intensity": "medium",
                "theme": "discovery",
            },
            "example_content": "小众展览 / 独立书店巡礼 / 街头摄影 / 城市漫步",
        },
        {
            "card_id": "card_solo_3",
            "title": "舒适休闲 · 简单舒服",
            "description": "不折腾，简单舒服地过一段时光",
            "tags": ["舒适", "简单", "低强度"],
            "implied_constraints": {
                "intent_mode": "relax",
                "activity_intensity": "low",
                "theme": "comfort",
            },
            "example_content": "商场闲逛 / 美食一人食 / 咖啡看书 / 公园发呆",
        },
    ],
}


def _map_group_type_to_card_key(group_type: str) -> str:
    """将系统内部 companion_context 映射到卡片模板的 group_type key。"""
    mapping = {
        "family_with_children": "家庭出行",
        "family_with_elderly": "家庭出行",
        "friends": "朋友聚会",
        "colleagues": "朋友聚会",
        "couple": "情侣约会",
        "solo": "独自一人",
    }
    return mapping.get(group_type, "独自一人")


# ==================== Round 1: 卡片 tag 小红书化 ====================

# 槽位 → 小红书风格短词候选表。每个槽位提供 2-3 个措辞，按卡片顺序轮换避免雷同。
_SLOT_TO_PHRASES: Dict[str, Dict[Any, List[str]]] = {
    "time_window": {
        "morning": ["早起党专属", "上午人少", "一早就开门"],
        "afternoon": ["午后刚好", "下午茶时段", "下午黄金档"],
        "now": ["现在就冲", "说走就走"],
        "full_day": ["泡一整天", "全天不赶"],
    },
    "transportation": {
        "driving": ["自驾友好", "开车直达", "导航就到"],
        "transit": ["地铁直达", "出站就到", "公交方便"],
        "taxi": ["打车10分钟", "下车就是"],
        "bike_walk": ["走着就到", "骑车很顺"],
    },
    "parking_needed": {True: ["好停车不用愁", "停车直达", "车位很稳"]},
    "near_subway": {True: ["近地铁", "地铁口就在", "出站5分钟"]},
    "child_age": {
        "0-3": ["奶娃友好", "推车无障碍", "小宝可冲"],
        "4-6": ["遛娃神地", "小朋友玩疯", "学龄前完美"],
        "7-12": ["小学娃天堂", "大娃也爱", "能放手玩"],
        "12+": ["青少年都爱"],
    },
    "parent_child": {True: ["亲子绝配", "宝藏遛娃地", "带娃首选"]},
    "low_energy": {True: ["佛系不折腾", "躺平友好", "不赶节奏"]},
    "photo_spot": {True: ["出片绝了", "随手出大片", "镜头不踩雷"]},
    "atmosphere": {
        "romantic": ["氛围拉满", "约会神地", "心动局"],
        "quiet": ["安静私藏", "不被打扰", "岁月静好"],
        "lively": ["氛围在线", "热闹起来", "场子拉满"],
    },
    "pet_allowed": {True: ["带毛孩子绝配", "宠物友好", "狗狗能进"]},
    "budget_level": {
        "low": ["白菜价能打", "性价比拉满", "钱包零压力"],
        "medium": ["人均100+", "不贵能吃饱", "日常局合适"],
        "medium_high": ["人均200随便点", "200档稳", "舍得吃"],
        "high": ["人均300+ 值", "高消享受", "体验值回"],
    },
    "cuisine_type": {
        "hotpot": ["火锅yyds", "火锅局必备"],
        "japanese": ["日料天花板", "日料真香"],
        "cantonese": ["粤菜真香", "粤味地道"],
        "western": ["西餐氛围正", "西餐拿捏"],
        "bbq": ["烧烤局必备", "撸串绝配"],
    },
    "food_preference": {
        "healthy": ["健康轻食", "沙拉绝绝子", "轻食友好"],
        "hotpot": ["火锅yyds", "火锅局必备"],
        "japanese": ["日料天花板", "日料真香"],
        "cantonese": ["粤菜真香", "粤味地道"],
        "western": ["西餐氛围正", "西餐拿捏"],
        "bbq": ["烧烤局必备", "撸串绝配"],
    },
    "people_count": {
        1: ["一个人也美"],
        2: ["两人刚好", "二人局舒服"],
        "3-5": ["小团出行", "几个人刚好"],
        "6+": ["团建神地", "大局开包", "人多也镇得住"],
    },
}

# 显示在卡片上的槽位优先级：用户主动通过小猜问选过的偏好排前面，
# 结构化的时间/交通排后面，确保用户最关心的事实先被看到。
_TAG_SLOT_PRIORITY = [
    "photo_spot",
    "atmosphere",
    "child_age",
    "parent_child",
    "low_energy",
    "pet_allowed",
    "budget_level",
    "cuisine_type",
    "food_preference",
    "people_count",
    "time_window",
    "transportation",
    "parking_needed",
    "near_subway",
]


def _has_overlap(tag: str, haystack: str, min_len: int = 2) -> bool:
    """tag 的任意 min_len 字窗口出现在 haystack 中即视为重复。"""
    if not tag or not haystack or len(tag) < min_len:
        return False
    for i in range(len(tag) - min_len + 1):
        if tag[i:i + min_len] in haystack:
            return True
    return False


def _derive_xhs_tags(
    card: Dict[str, Any],
    idx: int,
    structured_slots: Dict[str, Any],
    user_modifications: Dict[str, Any],
    used_phrases: Optional[set] = None,
    max_tags: int = 3,
) -> List[str]:
    """
    根据用户已提供的槽位事实，为单张卡片生成 3 个小红书风格 tag。

    规则：
    - 仅使用用户实际给出的槽位（Q1 + 小猜问）
    - driving 自动派生 parking_needed，transit 自动派生 near_subway
    - 同槽位对不同卡片优先用候选表里没用过的措辞，避免三卡雷同
    - 过滤掉与 title / description / example_content 有 2 字以上重叠的措辞
    - 过滤掉与已选 tag 有 2 字以上重叠的措辞，避免一张卡内部重复
    - 不足 2 个时回退到 card["tags"]，避免空 chips
    """
    if used_phrases is None:
        used_phrases = set()

    facts: Dict[str, Any] = {}
    for slot in ("time_window", "transportation"):
        v = (structured_slots or {}).get(slot)
        if v:
            facts[slot] = v
    if facts.get("transportation") == "driving":
        facts.setdefault("parking_needed", True)
    if facts.get("transportation") == "transit":
        facts.setdefault("near_subway", True)
    for k, v in (user_modifications or {}).items():
        if v is None or v == "" or v == [] or v == {}:
            continue
        facts[k] = v

    haystack = " ".join(filter(None, [
        card.get("title", ""),
        card.get("description", ""),
        card.get("example_content", ""),
    ]))

    chosen: List[str] = []
    for slot in _TAG_SLOT_PRIORITY:
        if slot not in facts:
            continue
        value = facts[slot]
        candidates = _SLOT_TO_PHRASES.get(slot, {}).get(value)
        if not candidates:
            continue
        avail = [c for c in candidates if not _has_overlap(c, haystack)]
        avail = [c for c in avail if not any(_has_overlap(c, t) for t in chosen)]
        if not avail:
            continue
        # 优先选其他卡片还没用过的措辞，让三张卡 tags 不雷同
        unused = [c for c in avail if c not in used_phrases]
        pick_pool = unused if unused else avail
        tag = pick_pool[idx % len(pick_pool)]
        chosen.append(tag)
        used_phrases.add(tag)
        if len(chosen) >= max_tags:
            break

    if len(chosen) < 2:
        return card.get("tags", [])
    return chosen


def generate_template_cards(
    group_type: str,
    user_modifications: Optional[Dict[str, Any]] = None,
    additional_query: Optional[str] = None,
    structured_slots: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Round 1: 生成三张泛方案卡片。

    根据用户已选择的 group_type 返回对应的 3 张风格卡片，
    每张卡片包含标题、描述、标签、隐含约束和示例内容。
    同时根据 additional_query（小猜问搜索词）和 user_modifications（累积槽位）
    对卡片进行相关性排序和个性化定制。
    用户选择其中一张后进入 Round 2。

    Args:
        group_type: 同行人类型（内部 companion_context 格式，如 family_with_children）
        user_modifications: 用户修改的槽位值（从小猜问中来）
        additional_query: 用户附加的自然语言输入（小猜问搜索词）
        structured_slots: 结构化槽位（time_window, transportation 等）

    Returns:
        {"round": 1, "output_type": "template_cards", "data": {"cards": [...]}}
    """
    card_key = _map_group_type_to_card_key(group_type)
    cards = deepcopy(TEMPLATE_CARD_DEFS.get(card_key, TEMPLATE_CARD_DEFS["独自一人"]))

    mods = user_modifications or {}
    slots = structured_slots or {}

    # 根据搜索词和槽位信息对卡片进行相关性排序和定制
    cards = _rank_cards_by_context(cards, additional_query, mods, slots)

    # 给排名第一的卡片加上推荐标记
    if cards:
        cards[0]["recommended"] = True

    # 用用户实际提供的槽位生成小红书风格 tag，覆盖原硬编码 tags
    used_phrases: set = set()
    for idx, card in enumerate(cards):
        card["tags"] = _derive_xhs_tags(card, idx, slots, mods, used_phrases=used_phrases)

    return {
        "round": 1,
        "output_type": "template_cards",
        "data": {
            "group_type": card_key,
            "group_type_key": group_type,
            "cards": cards,
            "user_modifications": mods,
            "additional_query": additional_query,
        },
    }


# ==================== 卡片排序与定制 ====================

# 搜索词 → 卡片特征的关键词映射，用于计算卡片与搜索意图的相关性
_CARD_KEYWORD_SCORES: Dict[str, Dict[str, float]] = {
    # 家庭出行卡片的关键词权重
    "card_family_1": {
        "室内": 2.0, "商场": 2.0, "轻松": 1.5, "不累": 1.5, "近": 1.5, "一站式": 2.0,
        "亲子": 1.0, "儿童": 1.5, "科技馆": 2.0, "乐园": 1.5, "雨天": 1.0, "凉快": 1.0,
        "简单": 1.0, "方便": 1.0, "顺路": 1.0, "吃饭": 0.5,
    },
    "card_family_2": {
        "互动": 2.0, "参与": 2.0, "动手": 2.0, "科学": 1.5, "手工": 2.0, "体验": 1.5,
        "沉浸": 2.0, "玩": 1.0, "孩子": 1.0, "实验": 1.5, "制作": 1.5,
        "创造": 1.5, "活动": 0.5,
    },
    "card_family_3": {
        "新鲜": 2.0, "特别": 2.0, "小众": 2.0, "记忆": 1.5, "不一样": 1.5,
        "独特": 2.0, "网红": 1.0, "打卡": 1.0, "快闪": 2.0, "展": 1.0,
        "特色": 1.5, "主题": 1.0, "创新": 1.5,
    },
    # 朋友聚会卡片的关键词权重
    "card_friends_1": {
        "散步": 2.0, "逛": 2.0, "走走": 2.0, "轻松": 1.5, "户外": 1.5, "拍照": 1.5,
        "Citywalk": 2.0, "滨江": 2.0, "路边": 1.0, "便宜": 1.0, "省钱": 1.0,
        "随意": 1.5, "灵活": 1.5, "咖啡": 1.0, "休闲": 1.0,
    },
    "card_friends_2": {
        "玩": 1.5, "互动": 2.0, "竞技": 2.0, "密室": 2.0, "剧本杀": 2.0, "桌游": 2.0,
        "游戏": 1.5, "运动": 1.5, "保龄球": 2.0, "比赛": 1.5, "一起": 1.0,
        "团队": 1.5, "挑战": 1.5, "刺激": 1.0, "手工": 1.5,
    },
    "card_friends_3": {
        "吃": 2.0, "喝": 1.5, "美食": 2.0, "餐厅": 2.0, "聚餐": 2.0, "酒吧": 2.0,
        "喝酒": 2.0, "火锅": 2.0, "日料": 2.0, "烧烤": 2.0, "粤菜": 2.0,
        "甜点": 1.0, "下午茶": 1.5, "坐坐": 2.0, "聊天": 1.5, "氛围": 1.0,
    },
    # 情侣约会卡片的关键词权重
    "card_couple_1": {
        "浪漫": 2.0, "仪式感": 2.0, "氛围": 1.5, "夜景": 1.5, "江景": 2.0,
        "烛光": 2.0, "景观": 1.5, "晚餐": 1.5, "高级": 1.0, "精致": 1.5,
        "纪念日": 2.0, "特别的日子": 2.0, "出片": 1.0, "拍照": 1.0,
    },
    "card_couple_2": {
        "互动": 2.0, "一起做": 2.0, "体验": 1.5, "手工": 2.0, "陶艺": 2.0,
        "烘焙": 2.0, "画画": 2.0, "制作": 1.5, "双人": 2.0, "合作": 1.5,
        "共同": 1.5, "回忆": 1.0,
    },
    "card_couple_3": {
        "散步": 2.0, "逛": 1.5, "公园": 2.0, "咖啡": 2.0, "书店": 2.0,
        "慢": 1.5, "悠闲": 2.0, "轻松": 1.5, "安静": 1.5, "舒服": 1.5,
        "不赶": 1.5, "随便": 1.5, "随心": 2.0,
    },
    # 独自一人卡片的关键词权重
    "card_solo_1": {
        "放松": 2.0, "充电": 2.0, "安静": 1.5, "SPA": 2.0, "按摩": 2.0, "温泉": 2.0,
        "治愈": 2.0, "独处": 2.0, "休息": 1.5, "泡汤": 2.0, "影院": 1.5,
        "看书": 1.5, "犒劳": 2.0, "享受": 1.5,
    },
    "card_solo_2": {
        "探索": 2.0, "发现": 2.0, "新鲜": 1.5, "展览": 2.0, "摄影": 1.5,
        "拍照": 1.5, "小众": 2.0, "城市": 1.0, "漫步": 1.0, "充实": 1.5,
        "文艺": 1.5, "艺术": 1.5, "文化": 1.5,
    },
    "card_solo_3": {
        "简单": 2.0, "舒服": 2.0, "懒": 2.0, "商场": 2.0, "发呆": 2.0,
        "闲逛": 2.0, "一人食": 2.0, "咖啡": 1.5, "看书": 1.5, "不折腾": 2.0,
        "轻松": 1.5, "随便": 1.5,
    },
}

# 槽位偏好 → 卡片隐含约束的匹配权重
_SLOT_TO_CARD_PREFERENCE: Dict[str, Dict[str, float]] = {
    "activity_preference": {
        "outdoor": {"card_family_1": -0.5, "card_family_2": 1.0, "card_family_3": 0.5,
                     "card_friends_1": 2.0, "card_friends_2": 0.5,
                     "card_couple_3": 2.0, "card_solo_2": 1.5},
        "culture": {"card_family_2": 1.0, "card_family_3": 2.0,
                    "card_solo_2": 2.0},
        "food": {"card_friends_3": 3.0, "card_couple_1": 1.5,
                 "card_solo_3": 1.0},
        "relax": {"card_family_1": 2.0, "card_friends_1": 2.0,
                  "card_couple_3": 2.0, "card_solo_1": 2.0, "card_solo_3": 1.5},
        "indoor": {"card_family_1": 2.0, "card_family_2": 1.5,
                   "card_friends_2": 1.5, "card_solo_1": 1.5},
    },
    "budget_level": {
        "low": {"card_friends_1": 2.0, "card_couple_3": 1.5, "card_solo_3": 1.5,
                "card_couple_1": -1.0},
        "high": {"card_couple_1": 2.0, "card_friends_3": 1.0, "card_family_3": 1.0,
                 "card_solo_1": 1.0},
    },
    "atmosphere": {
        "quiet": {"card_solo_1": 2.0, "card_couple_3": 2.0, "card_family_1": 1.5},
        "lively": {"card_friends_2": 2.0, "card_friends_3": 2.0, "card_family_2": 1.5},
        "romantic": {"card_couple_1": 3.0, "card_couple_2": 1.0},
    },
}


def _rank_cards_by_context(
    cards: List[Dict[str, Any]],
    additional_query: Optional[str],
    user_modifications: Dict[str, Any],
    structured_slots: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    根据搜索词和槽位信息对卡片进行相关性排序。

    排序依据：
    1. additional_query（小猜问搜索词）与卡片关键词的匹配度
    2. user_modifications（累积槽位）与卡片隐含约束的匹配度
    3. structured_slots（time_window, transportation）与卡片特征的匹配度

    返回按相关性从高到低排序的卡片列表。
    """
    if not additional_query and not user_modifications and not structured_slots:
        return cards

    scored = []
    for card in cards:
        card_id = card["card_id"]
        score = 0.0
        match_details: List[str] = []

        # 1. 搜索词匹配
        if additional_query:
            kw_scores = _CARD_KEYWORD_SCORES.get(card_id, {})
            for keyword, weight in kw_scores.items():
                if keyword in additional_query:
                    score += weight
                    match_details.append(f"关键词「{keyword}」+{weight:.1f}")

        # 2. 槽位偏好匹配
        for slot_name, preference_map in _SLOT_TO_CARD_PREFERENCE.items():
            slot_value = user_modifications.get(slot_name)
            if slot_value and card_id in preference_map.get(slot_value, {}):
                bonus = preference_map[slot_value][card_id]
                score += bonus
                match_details.append(f"偏好「{slot_name}={slot_value}」{bonus:+.1f}")

        # 3. 结构化槽位匹配
        time_window = structured_slots.get("time_window")
        if time_window:
            if time_window == "morning" and "全天" not in str(card.get("tags", [])):
                if card_id in ("card_family_2", "card_friends_2", "card_solo_2"):
                    score += 0.5  # 上午适合互动/探索类
            elif time_window == "full_day":
                if card_id in ("card_family_2", "card_friends_2", "card_couple_2"):
                    score += 0.5  # 全天适合深度体验

        transportation = structured_slots.get("transportation")
        if transportation == "transit":
            # 地铁出行偏好市内/短途
            if any(t in str(card.get("tags", [])) for t in ["短车程", "灵活", "轻松"]):
                score += 0.5
        elif transportation == "driving":
            # 自驾可以去远一点/特别的地方
            if any(t in str(card.get("tags", [])) for t in ["新鲜", "小众", "探索"]):
                score += 0.5

        scored.append((score, match_details, card))

    # 按分数降序排列
    scored.sort(key=lambda x: x[0], reverse=True)

    # 如果所有卡分数相同，保持原始顺序
    if scored and all(s[0] == scored[0][0] for s in scored):
        return cards

    return [card for _, _, card in scored]


# ==================== Round 2: 用户选择泛方案 ====================

def select_card_and_lock(
    card_id: str,
    group_type: str,
    current_slots: Dict[str, Any],
    user_additional_input: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Round 2: 用户选择泛方案卡片后锁定约束。

    合并卡片隐含约束 + 现有槽位 + 用户附加输入，生成 locked_constraints，
    返回确认信息并指示下一步 action。

    Args:
        card_id: 用户选择的卡片 ID
        group_type: 同行人类型
        current_slots: 当前已收集的槽位
        user_additional_input: 用户附加的自然语言输入

    Returns:
        {"round": 2, "output_type": "selection_confirmed", "data": {...}}
    """
    card_key = _map_group_type_to_card_key(group_type)
    cards = TEMPLATE_CARD_DEFS.get(card_key, [])

    # 查找选中的卡片
    selected_card = None
    for card in cards:
        if card["card_id"] == card_id:
            selected_card = card
            break

    if not selected_card:
        # 在所有卡片组中查找
        for group_cards in TEMPLATE_CARD_DEFS.values():
            for card in group_cards:
                if card["card_id"] == card_id:
                    selected_card = card
                    break
            if selected_card:
                break

    if not selected_card:
        return {
            "round": 2,
            "output_type": "selection_confirmed",
            "data": {
                "error": f"未找到卡片: {card_id}",
                "locked_constraints": current_slots,
                "next_action": "retry",
            },
        }

    # 合并约束：现有槽位 → 卡片隐含约束 → 用户附加输入
    locked = {**current_slots}
    implied = selected_card.get("implied_constraints", {})

    # 合并隐含约束（不覆盖已有的明确用户选择）
    for key, value in implied.items():
        if key not in locked or locked[key] is None:
            locked[key] = value

    # 解析用户附加输入中的约束
    if user_additional_input:
        extra = _parse_user_input_constraints(user_additional_input)
        locked.update(extra)

    return {
        "round": 2,
        "output_type": "selection_confirmed",
        "data": {
            "selected_card_id": card_id,
            "selected_card_title": selected_card["title"],
            "locked_constraints": locked,
            "implied_from_card": implied,
            "user_additional_input": user_additional_input,
            "next_action": "search_poi",
        },
    }


def _parse_user_input_constraints(text: str) -> Dict[str, Any]:
    """从用户自然语言输入中解析约束值。"""
    constraints: Dict[str, Any] = {}

    # 车程/时间约束
    match = re.search(r'(\d+)\s*分钟', text)
    if match:
        constraints["max_travel_time"] = int(match.group(1))

    # 预算
    if re.search(r'便宜|省钱|实惠|人均100|100以内', text):
        constraints["budget"] = "low"
    elif re.search(r'贵点|高端|精致|人均[3-9]\d\d|预算充足', text):
        constraints["budget"] = "high"
    elif re.search(r'人均[1-2]\d\d|中等', text):
        constraints["budget"] = "medium"

    # 距离
    if re.search(r'附近|离家近|不要太远|不远|近一点', text):
        constraints["travel_radius"] = "short"
    elif re.search(r'远点|远一些|出去', text):
        constraints["travel_radius"] = "far"

    # 氛围
    if re.search(r'安静|清静|不要太吵', text):
        constraints["atmosphere"] = "quiet"
    elif re.search(r'热闹|气氛好|嗨', text):
        constraints["atmosphere"] = "lively"
    elif re.search(r'浪漫|仪式感', text):
        constraints["atmosphere"] = "romantic"

    # 强度
    if re.search(r'轻松|不累|少走路|懒', text):
        constraints["activity_intensity"] = "low"

    # 室内外
    if re.search(r'室内|商场|不外', text):
        constraints["indoor_outdoor"] = "indoor"
    elif re.search(r'户外|公园|外面|透气|走走', text):
        constraints["indoor_outdoor"] = "outdoor"

    return constraints


# ==================== 跳步逻辑 ====================

def check_skip_possible(
    user_input: str,
    current_slots: Dict[str, Any],
) -> Dict[str, Any]:
    """
    判断是否可跳过某些 Round。

    当用户输入包含足够信息时，可以跳过部分交互轮次直接进入后续阶段。

    Returns:
        {"can_skip": bool, "target_round": int|None, "reason": str}
    """
    text = user_input.lower()

    # 检查是否明确了具体 POI（必须是指定名称的地点，不能是泛指动词）
    poi_keywords = [
        "博物馆", "公园", "商场", "乐园", "动物园",
        "美术馆", "展览", "科技馆", "水族馆", "海洋馆",
        "世纪公园", "迪士尼", "外滩", "南京路",
        "来福士", "大悦城", "正大", "恒隆", "新天地",
        "自然博物馆", "天文馆", "植物园", "古镇",
    ]
    has_specific_poi = any(kw in user_input for kw in poi_keywords)

    # 检查是否有时间信息
    has_time = any(kw in text for kw in [
        "今天", "明天", "周末", "周六", "周日",
        "下午", "晚上", "上午",
    ])

    # 检查是否有人员信息
    has_people = any(kw in text for kw in [
        "孩子", "朋友", "老婆", "老公", "父母",
        "一个人", "情侣", "同事",
    ])

    # 检查是否有交通信息
    has_transport = any(kw in text for kw in [
        "开车", "自驾", "地铁", "打车", "骑车", "步行",
    ])

    # 已收集的槽位
    slots = current_slots or {}
    has_group_type = bool(slots.get("group_type"))
    has_time_slot = bool(slots.get("time_slot"))
    has_mobility = bool(slots.get("mobility"))

    # 场景 1: 明确 POI + 时间 → 直达 Round 3
    if has_specific_poi and (has_time or has_time_slot):
        return {
            "can_skip": True,
            "target_round": 3,
            "reason": "用户已明确具体目的地和时间，可直接生成方案",
        }

    # 场景 2: 明确场景+偏好 → 跳过 Round 0，直达 Round 1
    if has_people and has_time:
        return {
            "can_skip": True,
            "target_round": 1,
            "reason": "用户已明确场景和时间偏好，跳过槽位收集和小猜问",
        }

    # 场景 3: 完整信息 → 跳过 Round 0 和 Round 1，直达 Round 2
    if has_people and has_time and has_transport:
        return {
            "can_skip": True,
            "target_round": 2,
            "reason": "用户已提供完整信息，跳过槽位收集、小猜问和泛方案",
        }

    return {"can_skip": False, "target_round": None, "reason": ""}


def extract_all_slots(user_input: str) -> Dict[str, Any]:
    """从用户自由文本中一次性提取所有可能的槽位值。"""
    slots: Dict[str, Any] = {}

    # group_type
    if re.search(r'家庭|带娃|孩子|亲子|宝宝', user_input):
        slots["group_type"] = "家庭出行"
    elif re.search(r'朋友|闺蜜|兄弟|哥们|搭子', user_input):
        slots["group_type"] = "朋友聚会"
    elif re.search(r'情侣|约会|女朋友|男朋友|二人世界', user_input):
        slots["group_type"] = "情侣约会"
    elif re.search(r'一个人|自己|独自|单独|散心', user_input):
        slots["group_type"] = "独自一人"

    # time_slot
    if re.search(r'今天', user_input):
        slots["time_slot"] = "今天"
    elif re.search(r'明天', user_input):
        slots["time_slot"] = "明天"
    elif re.search(r'周末|周六|周日', user_input):
        slots["time_slot"] = "本周末"

    # mobility
    if re.search(r'自驾|开车|自己开', user_input):
        slots["mobility"] = "自驾"
    elif re.search(r'打车|叫车|网约车|滴滴', user_input):
        slots["mobility"] = "打车"
    elif re.search(r'地铁|公交|坐地铁', user_input):
        slots["mobility"] = "公共交通"

    # child_age
    match = re.search(r'(\d+)\s*岁', user_input)
    if match:
        slots["child_age"] = int(match.group(1))

    return slots


# ==================== Round X: 槽位补全引导 ====================

def should_insert_round_x(
    current_slots: Dict[str, Any],
    round_count: int,
) -> Tuple[bool, List[str]]:
    """
    判断是否需要插入 Round X（槽位补全）。

    Returns:
        (是否需要插入, 缺失的必填槽位列表)
    """
    group_type = current_slots.get("group_type", "家庭出行")
    required = REQUIRED_SLOTS.get(group_type, REQUIRED_SLOTS["家庭出行"])
    missing = [s for s in required if s not in current_slots or current_slots[s] is None]

    if missing and round_count < BENCHMARK["max_rounds"]:
        return True, missing
    return False, []


def generate_slot_guidance(missing_slot: str) -> Dict[str, Any]:
    """
    为缺失的单个槽位生成引导选项。

    Returns:
        Round X 的输出格式，包含 guidance_type 和选项列表
    """
    guidance_map = {
        "child_age": {
            "missing_slot": "child_age",
            "display_name": "孩子多大",
            "guidance_type": "options",
            "options": [
                {"value": "3-6", "label": "3-6岁（学龄前）"},
                {"value": "7-12", "label": "7-12岁（小学）"},
                {"value": "13+", "label": "13岁以上"},
            ],
            "hint": "孩子年龄会影响活动推荐哦",
        },
        "time_slot": {
            "missing_slot": "time_slot",
            "display_name": "什么时候",
            "guidance_type": "options",
            "options": [
                {"value": "今天", "label": "今天"},
                {"value": "明天", "label": "明天"},
                {"value": "本周末", "label": "本周末"},
            ],
            "hint": "选个时间，帮你安排",
        },
        "mobility": {
            "missing_slot": "mobility",
            "display_name": "怎么过去",
            "guidance_type": "options",
            "options": [
                {"value": "自驾", "label": "自驾"},
                {"value": "打车", "label": "打车"},
                {"value": "公共交通", "label": "地铁/公交"},
            ],
            "hint": "交通方式会影响活动范围",
        },
        "group_type": {
            "missing_slot": "group_type",
            "display_name": "和谁一起",
            "guidance_type": "options",
            "options": [
                {"value": "家庭出行", "label": "家庭出行"},
                {"value": "朋友聚会", "label": "朋友聚会"},
                {"value": "情侣约会", "label": "情侣约会"},
                {"value": "独自一人", "label": "独自一人"},
            ],
            "hint": "和谁一起决定了活动类型哦",
        },
    }

    guidance = guidance_map.get(missing_slot, {
        "missing_slot": missing_slot,
        "display_name": missing_slot,
        "guidance_type": "free_input",
        "placeholder": f"请填写{missing_slot}",
        "optional": missing_slot not in ["group_type", "time_slot", "mobility"],
    })

    return {
        "round": "X",
        "output_type": "slot_guidance",
        "data": guidance,
    }


# ==================== 防死循环 ====================

def check_loop_risk(session: SessionState) -> Dict[str, Any]:
    """
    检测会话是否陷入死循环。

    Returns:
        {"action": "continue"|"force_complete"|"use_defaults"|"skip_question"|"provide_defaults",
         "reason": str}
    """
    # 1. 总轮次检测
    if session.current_round >= BENCHMARK["max_rounds"]:
        return {"action": "force_complete", "reason": "max_rounds_exceeded"}

    # 2. Round X 次数检测
    if session.slot_guidance_count >= BENCHMARK["max_slot_guidance"]:
        return {"action": "use_defaults", "reason": "slot_guidance_exceeded"}

    # 3. 相同问题重复检测
    if session.last_question and session.current_question:
        if session.last_question == session.current_question:
            session.repeat_question_count += 1
            if session.repeat_question_count >= BENCHMARK["max_same_question"]:
                return {"action": "skip_question", "reason": "question_repeated"}
        else:
            session.repeat_question_count = 0

    # 4. 用户无响应检测
    if session.no_response_count >= 2:
        return {"action": "provide_defaults", "reason": "user_inactive"}

    return {"action": "continue", "reason": ""}


def fallback_strategy(session: SessionState, reason: str) -> Dict[str, Any]:
    """
    触发降级策略时的处理。

    Returns:
        降级后的输出数据
    """
    if reason == "max_rounds_exceeded":
        return {
            "action": "force_complete",
            "message": "已达到最大交互轮次，使用当前信息生成方案",
            "slots": fill_with_defaults(session.slots),
        }

    elif reason == "slot_guidance_exceeded":
        filled = fill_with_defaults(session.slots)
        return {
            "action": "use_defaults",
            "message": "槽位引导次数已达上限，使用默认值填充",
            "slots": filled,
        }

    elif reason == "user_inactive":
        return {
            "action": "provide_defaults",
            "message": "似乎你暂时不在，我帮你用默认偏好生成一个方案吧",
            "slots": fill_with_defaults(session.slots),
        }

    elif reason == "question_repeated":
        session.last_question = None
        return {
            "action": "skip_question",
            "message": "我们换个方向吧",
        }

    return {"action": "continue"}


def fill_with_defaults(slots: Dict[str, Any]) -> Dict[str, Any]:
    """用默认值填充缺失的槽位。"""
    filled = {**slots}
    group_type = filled.get("group_type", "家庭出行")

    if "child_age" not in filled and group_type == "家庭出行":
        filled["child_age"] = SLOT_DEFAULTS["child_age"]

    if "max_duration" not in filled:
        filled["max_duration"] = SLOT_DEFAULTS["max_duration"]

    if "budget" not in filled:
        filled["budget"] = SLOT_DEFAULTS["budget"]

    return filled


# ==================== 回溯处理 ====================

def handle_backtrack(modification: str) -> Dict[str, Any]:
    """
    处理用户对方案的修改请求，判断应回溯到哪个阶段。

    Args:
        modification: 用户修改内容

    Returns:
        {"action": "re_search"|"back_to_templates"|"restart", "scope": str, "target_state": State}
    """
    mod_type = classify_modification(modification)

    if mod_type == "minor_constraint":
        return {
            "action": "re_search",
            "scope": "partial",
            "target_state": State.PLAN_SEARCHING,
            "message": "好的，我按你的新要求重新搜索一下",
        }
    elif mod_type == "direction_change":
        return {
            "action": "back_to_templates",
            "target_state": State.TEMPLATE_CARDS,
            "message": "方向调整比较大，我们重新看看喜欢的风格？",
        }
    elif mod_type == "major_change":
        return {
            "action": "restart",
            "target_state": State.SLOT_COLLECTING,
            "message": "需求变化较大，我们从头来规划吧",
        }

    return {"action": "re_search", "scope": "partial", "target_state": State.PLAN_SEARCHING}


def classify_modification(text: str) -> str:
    """分类用户修改的类型。"""
    text_lower = text.lower()

    # 微调约束：改时间、改预算、加偏好
    minor_keywords = ["改", "换成", "换一个", "不要太贵", "近一点", "早一点", "晚一点",
                      "预算", "时间", "加一个", "再加"]
    if any(kw in text_lower for kw in minor_keywords):
        return "minor_constraint"

    # 方向变更：换类型、换风格
    direction_keywords = ["不要这种", "换种风格", "换类型", "不太喜欢", "换方向",
                          "不是这种", "想换", "换一类"]
    if any(kw in text_lower for kw in direction_keywords):
        return "direction_change"

    # 大变更：改人数、改场景、改地点
    major_keywords = ["不去", "换地方", "换城市", "不是周末", "不带孩子",
                      "改成", "重来", "重新规划"]
    if any(kw in text_lower for kw in major_keywords):
        return "major_change"

    return "minor_constraint"


# ==================== 修改意图解析（槽位更新） ====================

def parse_modification_slots(text: str, existing_slots: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    从用户修改文本中提取结构化的槽位更新。

    当用户在会话中手动输入"改成3个人""预算降一档""换吃日料"等文字时，
    解析具体意图并返回需要更新的槽位键值对，使最终方案与用户意图高度一致。

    Args:
        text: 用户输入的修改文本
        existing_slots: 当前已有的槽位（用于判断是否有变化）

    Returns:
        {
            "updated_slots": {slot_name: new_value, ...},  # 本次要更新的槽位
            "mod_type": "minor_constraint"|"direction_change"|"major_change",
            "parsed_intent": "修改了什么的人类可读说明",
        }
    """
    existing = existing_slots or {}
    text_lower = text.lower()
    updated: Dict[str, Any] = {}
    intents: List[str] = []

    # ── 人数 ──
    people_match = re.search(r'(\d+)\s*个?\s*人', text)
    if people_match:
        new_count = int(people_match.group(1))
        old_count = existing.get("people_count")
        if old_count != new_count:
            updated["people_count"] = new_count
            intents.append(f"人数 → {new_count}人")
    elif re.search(r'多加[一俩两三四五六七八九]|[一俩两三四五六七八九]\s*个?\s*人', text):
        # "多一个人"、"再加两人"
        num_map = {"一": 1, "俩": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8}
        for cn, num in num_map.items():
            if re.search(rf'多加{cn}|再加{cn}|{cn}\s*个?\s*人', text):
                old = existing.get("people_count", 0) or 0
                new_count = old + num
                updated["people_count"] = new_count
                intents.append(f"人数 +{num} → {new_count}人")
                break
    elif re.search(r'少[一俩两]个?\s*人|减[一俩两]个?\s*人', text):
        num_map = {"一": 1, "俩": 2, "两": 2}
        for cn, num in num_map.items():
            if re.search(rf'少{cn}|减{cn}', text):
                old = existing.get("people_count", 0) or 0
                new_count = max(1, old - num)
                updated["people_count"] = new_count
                intents.append(f"人数 -{num} → {new_count}人")
                break

    # ── 预算 ──
    if re.search(r'便宜|实惠|省钱|人均\s*100|100\s*以内|经济|预算低|低预算|预算别太|不要太贵|别太贵|低一点|预算低一点|省点|节省', text_lower):
        if existing.get("budget") != "low" and existing.get("budget_level") != "low":
            updated["budget"] = "low"
            updated["budget_level"] = "low"
            intents.append("预算 → 经济实惠")
    elif re.search(r'预算[高中]|贵点|高端|精致|人均\s*[3-9]\d\d|预算充足|档次高|升级|预算高|高一点|预算高一|升一档|加点预算|吃好一点|吃好点', text_lower):
        if existing.get("budget") != "high" and existing.get("budget_level") != "high":
            updated["budget"] = "high"
            updated["budget_level"] = "high"
            intents.append("预算 → 高")
    elif re.search(r'人均\s*[1-2]\d\d|中等|预算中|正常', text_lower):
        if existing.get("budget") != "medium":
            updated["budget"] = "medium"
            updated["budget_level"] = "medium"
            intents.append("预算 → 中等")

    # ── 菜系/饮食偏好 ──
    cuisine_map = {
        "火锅": "hotpot", "日料": "japanese", "日式": "japanese", "寿司": "japanese",
        "粤菜": "cantonese", "本帮菜": "cantonese", "西餐": "western", "牛排": "western",
        "烧烤": "bbq", "撸串": "bbq", "韩料": "korean", "韩国": "korean",
        "泰国": "thai", "东南亚": "thai", "轻食": "healthy", "健康餐": "healthy",
        "小吃": "street_food", "咖啡": "cafe", "甜品": "cafe", "下午茶": "cafe",
        "中餐": "chinese",
    }
    for kw, cv in cuisine_map.items():
        if re.search(rf'吃{kw}|换{kw}|改成{kw}|要{kw}|想.*{kw}', text_lower):
            if existing.get("cuisine_type") != cv and existing.get("food_preference") != cv:
                updated["cuisine_type"] = cv
                updated["food_preference"] = cv
                intents.append(f"菜系 → {kw}")
                break

    # ── 距离/车程 ──
    distance_match = re.search(r'(\d+)\s*分钟', text)
    if distance_match:
        new_dist = int(distance_match.group(1))
        updated["max_travel_time"] = new_dist
        intents.append(f"车程 → {new_dist}分钟")
    if re.search(r'附近|离家近|不要太远|不远|近一点|近些', text_lower):
        updated["travel_radius"] = "short"
        intents.append("距离 → 近")
    elif re.search(r'远点|远一些|远一点|出去', text_lower):
        updated["travel_radius"] = "far"
        intents.append("距离 → 远")

    # ── 氛围 ──
    if re.search(r'安静|清静|不要太吵|安静点|安静些', text_lower):
        updated["atmosphere"] = "quiet"
        intents.append("氛围 → 安静")
    elif re.search(r'热闹|气氛好|嗨|人多|热闹点', text_lower):
        updated["atmosphere"] = "lively"
        intents.append("氛围 → 热闹")
    elif re.search(r'浪漫|仪式感|有情调', text_lower):
        updated["atmosphere"] = "romantic"
        intents.append("氛围 → 浪漫")

    # ── 室内/室外 ──
    if re.search(r'室内|商场|不外|不要户外|别户外|室内活动', text_lower):
        updated["indoor_outdoor"] = "indoor"
        intents.append("偏好 → 室内")
    elif re.search(r'户外|公园|外面|透气|走走|室外|户外活动', text_lower):
        updated["indoor_outdoor"] = "outdoor"
        intents.append("偏好 → 户外")

    # ── 强度 ──
    if re.search(r'轻松|不累|少走路|懒|不折腾|轻松点|不要太累|别太累|太累|不想累', text_lower):
        updated["activity_intensity"] = "low"
        updated["low_energy"] = True
        intents.append("强度 → 轻松")
    elif re.search(r'刺激|运动|徒步|爬山|体力|要动|动一动', text_lower):
        updated["activity_intensity"] = "medium"
        updated["low_energy"] = False
        intents.append("强度 → 中等")

    # ── 交通方式 ──
    if re.search(r'自驾|开车|自己开', text_lower):
        updated["mobility"] = "自驾"
        updated["transportation"] = "driving"
        updated["parking_needed"] = True
        intents.append("交通 → 自驾")
    elif re.search(r'打车|叫车|网约车|滴滴', text_lower):
        updated["mobility"] = "打车"
        updated["transportation"] = "taxi"
        intents.append("交通 → 打车")
    elif re.search(r'地铁|公交|坐地铁', text_lower):
        updated["mobility"] = "公共交通"
        updated["transportation"] = "transit"
        updated["near_subway"] = True
        intents.append("交通 → 公共交通")

    # ── 时间窗口 ──
    if re.search(r'上午|早上|早一点|早点', text_lower):
        updated["time_window"] = "morning"
        intents.append("时间 → 上午")
    elif re.search(r'下午|午后', text_lower):
        updated["time_window"] = "afternoon"
        intents.append("时间 → 下午")
    elif re.search(r'晚上|傍晚|晚餐|晚饭', text_lower):
        updated["time_window"] = "evening"
        intents.append("时间 → 晚上")
    elif re.search(r'全天|一整天|整天|全天候', text_lower):
        updated["time_window"] = "full_day"
        updated["time_slot"] = "full_day"
        intents.append("时间 → 全天")

    # ── 拍照 ──
    if re.search(r'拍照|出片|好看|打卡', text_lower):
        updated["photo_spot"] = True
        intents.append("偏好 → 拍照出片")
    elif re.search(r'不用拍照|不拍照|无所谓拍照', text_lower):
        updated["photo_spot"] = False
        intents.append("偏好 → 不要求拍照")

    # ── 亲子相关 ──
    if re.search(r'亲子|带娃|孩子.*岁|宝宝', text_lower):
        updated["parent_child"] = True
        child_match = re.search(r'(\d+)\s*岁', text)
        if child_match:
            updated["child_age"] = int(child_match.group(1))
            intents.append(f"孩子年龄 → {updated['child_age']}岁")
        intents.append("偏好 → 亲子友好")

    # ── 宠物 ──
    if re.search(r'宠物|带狗|带猫|遛狗|狗狗|猫咪', text_lower):
        updated["pet_allowed"] = True
        intents.append("偏好 → 宠物友好")

    mod_type = classify_modification(text)

    return {
        "updated_slots": updated,
        "mod_type": mod_type,
        "parsed_intent": "；".join(intents) if intents else "未识别到具体槽位变更",
    }


# ==================== Orchestrator 主控 ====================

class Orchestrator:
    """多轮对话编排器，管理完整交互流程的状态转移和 Skill 调度。"""

    def __init__(self, session_id: str = ""):
        import uuid
        self.session = SessionState(session_id=session_id or uuid.uuid4().hex[:12])

    # ---- Round 0: 槽位初始化 ----

    def init_slots(self) -> Dict[str, Any]:
        """Round 0 第一层：返回三个分类选项。"""
        self.session.transition("user_click")
        return {
            "round": 0,
            "stage": "slot_init",
            "output_type": "slot_options",
            "data": {
                "slots": [
                    {
                        "slot_id": "group_type",
                        "display_name": "和谁一起",
                        "options": GROUP_TYPE,
                        "selected": None,
                    },
                    {
                        "slot_id": "time_slot",
                        "display_name": "什么时候",
                        "options": TIME_SLOT,
                        "selected": None,
                    },
                    {
                        "slot_id": "mobility",
                        "display_name": "怎么过去",
                        "options": MOBILITY,
                        "selected": None,
                    },
                ]
            },
        }

    # ---- Round 0 Q2: 小猜问 ----

    @staticmethod
    def _slots_to_followup_format(slots: Dict[str, Any]) -> Dict[str, Any]:
        """将 Orchestrator 槽位格式映射为 generate_followup_questions 期望的格式。"""
        group_map = {
            "家庭出行": ["family_with_children"],
            "朋友聚会": ["friends"],
            "情侣约会": ["couple"],
            "独自一人": ["solo"],
        }
        time_map = {
            "今天": "now", "明天": "morning",
            "本周末": "full_day", "下周末": "full_day",
        }
        mobility_map = {
            "自驾": "driving", "打车": "taxi",
            "公共交通": "transit", "无偏好": "",
        }
        transport = mobility_map.get(slots.get("mobility", ""), "")
        context_modifiers = []
        if transport == "driving":
            context_modifiers.append("parking_needed")
        elif transport == "transit":
            context_modifiers.append("near_subway")

        return {
            "companion_context": group_map.get(slots.get("group_type", ""), ["solo"]),
            "time_window": time_map.get(slots.get("time_slot", ""), ""),
            "transportation": transport,
            "context_modifiers": context_modifiers,
        }

    def handle_slot_selection(self, selections: Dict[str, str]) -> Dict[str, Any]:
        """用户完成 Round 0 槽位选择后，更新槽位并触发小猜问。"""
        self.session.slots.update(selections)
        self.session.transition("slots_filled")

        # 生成实际的猜测句
        try:
            from prompts import generate_followup_questions
            followup_input = self._slots_to_followup_format(self.session.slots)
            followup_result = generate_followup_questions(followup_input)
            sentences = followup_result.get("sentences", [])
            completeness = followup_result.get("completeness", 1.0)
        except Exception as exc:
            logger.warning("小猜问生成失败，使用兜底: %s", exc)
            sentences = []
            completeness = 0.0

        return {
            "round": 0,
            "stage": "guess_questions",
            "output_type": "guess_sentences",
            "data": {
                "slots": self.session.slots,
                "sentences": sentences,
                "completeness": completeness,
            },
        }

    # ---- Round 1: 泛方案卡片 ----

    def handle_guess_selection(
        self,
        selected_q_id: str,
        user_modifications: Optional[Dict[str, Any]] = None,
        additional_query: Optional[str] = None,
    ) -> Dict[str, Any]:
        """用户选择小猜问后，进入 Round 1 生成泛方案卡片。"""
        # 合并用户修改到槽位
        mods = user_modifications or {}
        for key, value in mods.items():
            self.session.slots[key] = value

        self.session.user_selections.append({
            "round": 0,
            "q_id": selected_q_id,
            "modifications": mods,
        })

        self.session.transition("user_select")

        # 检查是否需要 Round X
        need_guidance, missing = should_insert_round_x(
            self.session.slots, self.session.current_round
        )
        if need_guidance:
            self.session.slot_guidance_count += 1
            return generate_slot_guidance(missing[0])

        # 生成泛方案卡片
        group_type = self.session.slots.get("group_type", "独自一人")
        return generate_template_cards(group_type, mods, additional_query)

    # ---- Round 2: 选择泛方案 ----

    def handle_card_selection(
        self,
        card_id: str,
        user_additional_input: Optional[str] = None,
    ) -> Dict[str, Any]:
        """用户选择泛方案卡片后，锁定约束。"""
        group_type = self.session.slots.get("group_type", "独自一人")

        self.session.user_selections.append({
            "round": 1,
            "card_id": card_id,
            "additional_input": user_additional_input,
        })

        self.session.transition("user_select")

        result = select_card_and_lock(
            card_id=card_id,
            group_type=group_type,
            current_slots=self.session.slots,
            user_additional_input=user_additional_input,
        )

        self.session.locked_constraints = result["data"].get("locked_constraints", {})
        return result

    # ---- Round 3: 搜索完成 ----

    def handle_plan_search_complete(self, plans: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Round 3 搜索完成，展示具体方案。"""
        self.session.candidate_plans = plans
        self.session.transition("search_complete")
        return {
            "round": 3,
            "output_type": "concrete_plans",
            "data": {
                "plans": plans,
                "locked_constraints": self.session.locked_constraints,
            },
        }

    # ---- Round 4: 确认方案 ----

    def handle_plan_confirmation(
        self,
        plan_id: str,
        user_feedback: Optional[str] = None,
    ) -> Dict[str, Any]:
        """用户确认具体方案后，触发小票生成。"""
        selected = None
        if self.session.candidate_plans:
            for plan in self.session.candidate_plans:
                if plan.get("plan_id") == plan_id:
                    selected = plan
                    break

        self.session.selected_plan = selected
        self.session.user_selections.append({
            "round": 3,
            "plan_id": plan_id,
            "feedback": user_feedback,
        })

        self.session.transition("user_confirm")
        return {
            "round": 3,
            "stage": "plan_confirmed",
            "output_type": "confirmation",
            "data": {
                "selected_plan_id": plan_id,
                "user_feedback": user_feedback,
                "next_action": "generate_receipt",
            },
        }

    # ---- 异常处理 ----

    def handle_modification(self, modification: str) -> Dict[str, Any]:
        """用户修改方案，解析意图→更新槽位→判断回溯目标。"""
        # 1. 解析用户修改意图，提取具体槽位更新
        parsed = parse_modification_slots(modification, self.session.slots)
        updated_slots = parsed.get("updated_slots", {})

        # 2. 将解析出的槽位更新应用到 session
        for key, value in updated_slots.items():
            self.session.slots[key] = value
            # 同步更新 locked_constraints，确保后续 agent 搜索使用最新约束
            if key in ("budget", "budget_level", "people_count", "cuisine_type", "food_preference",
                       "atmosphere", "indoor_outdoor", "activity_intensity", "low_energy",
                       "photo_spot", "pet_allowed", "parent_child", "child_age",
                       "mobility", "transportation", "parking_needed", "near_subway",
                       "max_travel_time", "travel_radius", "time_window", "time_slot"):
                self.session.locked_constraints[key] = value

        # 3. 判断回溯目标
        backtrack = handle_backtrack(modification)
        target_state = backtrack["target_state"]
        self.session.current_state = target_state

        return {
            "output_type": "backtrack",
            "data": {
                "action": backtrack["action"],
                "target_state": target_state.value,
                "message": backtrack["message"],
                "updated_slots": updated_slots,
                "parsed_intent": parsed.get("parsed_intent", ""),
                "current_slots": self.session.slots,
                "locked_constraints": self.session.locked_constraints,
            },
        }

    def get_state(self) -> Dict[str, Any]:
        """获取当前会话状态。"""
        return self.session.to_dict()
