"""
Round 4: 小票生成 + 分享语

在用户确认具体方案后，生成可视化的小票卡片和可转发的分享文案。
与 agent_harness 的 execute_plan 解耦——小票是纯展示层逻辑。
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional


# ==================== 小票卡片生成 ====================

def generate_receipt(
    plan: Dict[str, Any],
    locked_constraints: Optional[Dict[str, Any]] = None,
    user_feedback: Optional[str] = None,
) -> Dict[str, Any]:
    """
    根据用户确认的具体方案生成小票卡片。

    Args:
        plan: 选中的方案数据（来自 agent_harness 返回的 best_plan）
        locked_constraints: 锁定的约束条件（来自 Round 2）
        user_feedback: 用户确认时的反馈文字

    Returns:
        {"round": 4, "output_type": "receipt_card", "data": {"receipt": {...}, "share_text": "...", "actions": [...]}}
    """
    constraints = locked_constraints or {}
    plan_title = plan.get("title", "周末活动方案")
    timeline = plan.get("timeline", [])
    activities = plan.get("activities", [])
    restaurant = plan.get("restaurant", {})
    risks = plan.get("risks", [])
    total_duration = plan.get("total_duration_minutes", 240)
    score = plan.get("score", 0)

    # 提取关键信息
    activity_names = [a.get("name", "") for a in activities]
    restaurant_name = restaurant.get("name", "") if restaurant else ""
    restaurant_cuisine = restaurant.get("cuisine_type", "") if restaurant else ""

    # 构建摘要
    summary = _build_summary(
        timeline=timeline,
        constraints=constraints,
        activity_names=activity_names,
        restaurant_name=restaurant_name,
        restaurant_cuisine=restaurant_cuisine,
        total_duration_minutes=total_duration,
    )

    # 提取亮点
    highlights = _extract_highlights(
        plan=plan,
        activities=activities,
        restaurant=restaurant,
        risks=risks,
        score=score,
        constraints=constraints,
    )

    # 构建状态
    status = _build_status(
        activities=activities,
        restaurant=restaurant,
        timeline=timeline,
    )

    # 生成标题
    emoji_map = {
        "family_with_children": "🦕",
        "family_with_elderly": "🌿",
        "friends": "🎉",
        "couple": "💕",
        "solo": "☕",
        "colleagues": "🍻",
    }
    group_type = constraints.get("group_type", "")
    emoji = emoji_map.get(group_type, "📋")

    receipt = {
        "title": f"{emoji} {_build_receipt_title(plan_title, constraints)}",
        "summary": summary,
        "highlights": highlights[:4],  # 最多4个亮点
        "status": status,
        "score": score,
        "plan_id": plan.get("plan_id", ""),
    }

    # 生成分享语
    share_text = generate_share_text(plan, constraints, user_feedback)

    # 分享操作
    actions = get_share_actions(share_text)

    return {
        "round": 4,
        "output_type": "receipt_card",
        "data": {
            "receipt": receipt,
            "share_text": share_text,
            "actions": actions,
        },
    }


def _build_receipt_title(plan_title: str, constraints: Dict[str, Any]) -> str:
    """构建小票标题。"""
    group_type = constraints.get("group_type", "")
    time_slot = constraints.get("time_slot", "")

    if group_type == "家庭出行":
        prefix = "遛娃计划" if "孩子" in str(constraints) or constraints.get("child_age") else "家庭出行计划"
    elif group_type == "朋友聚会":
        prefix = "朋友聚会计划"
    elif group_type == "情侣约会":
        prefix = "约会计划"
    elif group_type == "独自一人":
        prefix = "独处时光计划"
    else:
        prefix = "出行计划"

    if time_slot:
        time_map = {"今天": "今天", "明天": "明天", "本周末": "本周末", "下周末": "下周末"}
        time_str = time_map.get(time_slot, time_slot)
        return f"{time_str}{prefix}"

    return f"{prefix}"


def _build_summary(
    timeline: List[Dict[str, Any]],
    constraints: Dict[str, Any],
    activity_names: List[str],
    restaurant_name: str,
    restaurant_cuisine: str,
    total_duration_minutes: int,
) -> Dict[str, str]:
    """构建小票摘要。"""
    # 时间信息
    if timeline:
        first_item = timeline[0]
        last_item = timeline[-1]
        start_time = first_item.get("time", "14:00").split("-")[0] if "-" in first_item.get("time", "") else "14:00"
        end_time = last_item.get("time", "18:00").split("-")[-1] if "-" in last_item.get("time", "") else "18:00"
        time_str = f"{start_time}出发，约{total_duration_minutes // 60}小时{total_duration_minutes % 60}分钟"
    else:
        time_str = f"约{total_duration_minutes // 60}小时"

    # 人员信息
    group_type = constraints.get("group_type", "")
    group_map = {
        "家庭出行": "家庭出行",
        "朋友聚会": "朋友聚会",
        "情侣约会": "两人",
        "独自一人": "一个人",
    }
    child_age = constraints.get("child_age")
    if child_age and group_type == "家庭出行":
        group_str = f"{group_map.get(group_type, '')}，孩子{child_age}岁"
    else:
        group_str = group_map.get(group_type, "")

    # 活动
    activity_str = " → ".join(activity_names) if activity_names else "未指定活动"

    # 餐饮
    if restaurant_name and restaurant_cuisine:
        dining_str = f"{restaurant_name}（{restaurant_cuisine}）"
    elif restaurant_name:
        dining_str = restaurant_name
    else:
        dining_str = "未指定餐厅"

    # 通勤
    mobility = constraints.get("mobility", "")
    travel_time = constraints.get("max_travel_time", "")
    mobility_map = {"自驾": "自驾", "打车": "打车", "公共交通": "地铁/公交"}
    mobility_str = mobility_map.get(mobility, mobility or "未指定")
    if travel_time:
        mobility_str += f"，单程{travel_time}分钟"

    # 预算
    budget = constraints.get("budget", "")
    if not budget and "restaurant" in str(constraints).lower():
        budget = "中等"
    budget_map = {"low": "经济实惠", "medium": "中等预算", "high": "预算充足"}
    budget_str = budget_map.get(budget, budget or "未指定")

    return {
        "time": time_str,
        "group": group_str,
        "activity": activity_str,
        "dining": dining_str,
        "mobility": mobility_str,
        "budget": budget_str,
    }


def _extract_highlights(
    plan: Dict[str, Any],
    activities: List[Dict[str, Any]],
    restaurant: Dict[str, Any],
    risks: List[str],
    score: float,
    constraints: Dict[str, Any],
) -> List[str]:
    """提取小票亮点。"""
    highlights = []

    recommendation_reason = plan.get("recommendation_reason", "")
    if recommendation_reason:
        # 拆分句号分隔的多条理由
        parts = [p.strip() for p in recommendation_reason.replace("。", ".").split(".") if p.strip()]
        highlights.extend(parts[:2])

    # 从活动提取亮点
    for activity in activities:
        name = activity.get("name", "")
        activity_type = activity.get("type", "")
        child_friendly = activity.get("child_friendly", False)

        if child_friendly and constraints.get("group_type") == "家庭出行":
            highlights.append(f"{name}亲子友好，孩子能玩住")
        elif activity_type == "museum":
            highlights.append(f"{name}既能玩又能学")
        elif activity_type == "park":
            highlights.append(f"{name}户外透气，放松身心")

    # 餐厅亮点
    if restaurant:
        r_name = restaurant.get("name", "")
        diet_friendly = restaurant.get("diet_friendly", False)
        if diet_friendly:
            highlights.append(f"{r_name}有健康轻食选择")

    # 从约束条件生成亮点
    if constraints.get("indoor_outdoor") == "indoor":
        highlights.append("全程室内，不受天气影响")
    elif constraints.get("indoor_outdoor") == "outdoor":
        highlights.append("户外活动，呼吸新鲜空气")

    if constraints.get("intent_mode") == "relax":
        highlights.append("轻松不累，节奏舒适")

    if constraints.get("travel_radius") == "short":
        mobility = constraints.get("mobility", "")
        mobility_str = {"自驾": "开车", "打车": "打车", "公共交通": "地铁"}.get(mobility, "")
        if mobility_str:
            highlights.append(f"{mobility_str}路程短，不折腾")

    if constraints.get("atmosphere") == "romantic":
        highlights.append("氛围浪漫，适合约会")

    # 评分
    if score >= 85:
        highlights.append("综合评分优秀，推荐指数高")

    # 风险提示作为亮点反衬
    if not risks:
        highlights.append("无需预约排队，说走就走")

    # 去重
    seen = set()
    unique = []
    for h in highlights:
        if h not in seen:
            seen.add(h)
            unique.append(h)

    return unique


def _build_status(
    activities: List[Dict[str, Any]],
    restaurant: Dict[str, Any],
    timeline: List[Dict[str, Any]],
) -> Dict[str, str]:
    """构建小票状态信息。"""
    status = {}

    # 活动预约状态
    for activity in activities:
        name = activity.get("name", "")
        need_booking = activity.get("need_booking", False)
        if need_booking:
            status["活动预约"] = f"⏰ {name}需提前预约"
        else:
            status["活动入场"] = f"✅ {name}无需预约"

    # 餐厅状态
    if restaurant:
        r_name = restaurant.get("name", "")
        need_booking = restaurant.get("need_booking", True)
        if need_booking:
            # 查找用餐时间
            meal_time = ""
            for item in timeline:
                if item.get("type") == "meal":
                    meal_time = item.get("time", "").split("-")[0] if "-" in item.get("time", "") else ""
                    break
            if meal_time:
                status["餐厅"] = f"⏰ {r_name}建议{meal_time}取号"
            else:
                status["餐厅"] = f"⏰ {r_name}建议提前取号"
        else:
            status["餐厅"] = f"✅ {r_name}无需预约"

    # 停车
    status["停车"] = "✅ 目的地有停车场" if any("停车" in str(a) for a in activities) else "✅ 查看目的地停车信息"

    return status


# ==================== 分享语 ====================

def generate_share_text(
    plan: Dict[str, Any],
    constraints: Optional[Dict[str, Any]] = None,
    user_feedback: Optional[str] = None,
) -> str:
    """
    生成自然口语化的分享语，适合转发到微信。

    Args:
        plan: 方案数据
        constraints: 约束条件
        user_feedback: 用户反馈

    Returns:
        分享语文案
    """
    constraints = constraints or {}
    plan_title = plan.get("title", "")
    timeline = plan.get("timeline", [])
    activities = plan.get("activities", [])
    restaurant = plan.get("restaurant", {})
    total_duration = plan.get("total_duration_minutes", 240)

    # 提取关键信息
    activity_names = [a.get("name", "") for a in activities]
    restaurant_name = restaurant.get("name", "") if restaurant else ""

    # 时间
    if timeline:
        first_time = timeline[0].get("time", "14:00")
        start_time = first_time.split("-")[0] if "-" in first_time else "14:00"
    else:
        start_time = "14:00"

    hours = total_duration // 60

    # 根据场景生成不同的分享语风格
    group_type = constraints.get("group_type", "")
    templates = _get_share_templates(
        group_type=group_type,
        start_time=start_time,
        hours=hours,
        activity_names=activity_names,
        restaurant_name=restaurant_name,
        constraints=constraints,
        plan=plan,
    )

    # 选择最合适的模板
    if templates:
        return random.choice(templates)

    # 通用 fallback
    parts = []
    time_label = {"今天": "今天", "明天": "明天", "本周末": "周末"}.get(
        constraints.get("time_slot", ""), ""
    )
    if time_label:
        parts.append(f"{time_label}下午安排了")
    else:
        parts.append("下午安排了")

    if activity_names:
        parts.append(f"去{'，再去'.join(activity_names[:2])}")
    if restaurant_name:
        parts.append(f"在{restaurant_name}吃饭")

    parts.append(f"全程大概{hours}小时，轻松不累。")

    return "".join(parts)


def _get_share_templates(
    group_type: str,
    start_time: str,
    hours: int,
    activity_names: List[str],
    restaurant_name: str,
    constraints: Dict[str, Any],
    plan: Dict[str, Any],
) -> List[str]:
    """获取场景相关的分享语模板列表。"""
    activity_str = "和".join(activity_names[:2]) if activity_names else "活动"
    restaurant_str = restaurant_name or "餐厅"

    shared = []

    if group_type == "家庭出行":
        child_age = constraints.get("child_age", "")
        age_hint = f"孩子{child_age}岁" if child_age else "带娃"
        shared = [
            f"{'周末' if '周末' in str(constraints) else ''}下午安排好了！带{age_hint}去{activity_str}，听说不错应该能玩住。晚饭在{restaurant_str}吃。全程轻松不累。你看看行不行？",
            f"给{age_hint}安排了一个周末活动～去{activity_str}，晚点去{restaurant_str}吃饭。开车很快，不折腾。你看看这个安排？",
            f"安排了一个亲子出行！下午{start_time}出发，先去{activity_str}，然后{restaurant_str}吃晚饭。全程{hours}小时左右，节奏轻松。",
        ]
    elif group_type == "朋友聚会":
        shared = [
            f"周末安排好了！一起去{activity_str}，然后{restaurant_str}聚个餐。全程{hours}小时左右，轻松不赶。你们看看行不行？",
            f"整了一个周末出行计划～{start_time}出发，{activity_str} + {restaurant_str}。不折腾，边走边聊。来不来？",
            f"朋友们看过来！安排了{activity_str}，完事去{restaurant_str}吃一顿。大概{hours}小时，有空的一起～",
        ]
    elif group_type == "情侣约会":
        shared = [
            f"约会计划安排好啦～{start_time}出发，先去{activity_str}，再去{restaurant_str}。氛围不错，你觉得呢？",
            f"周末安排了一个约会，{activity_str} + {restaurant_str}，应该挺浪漫的。期待一下～",
            f"下午{start_time}见！安排了{activity_str}，然后{restaurant_str}晚餐。全程不赶，慢慢逛。",
        ]
    elif group_type == "独自一人":
        shared = [
            f"给自己安排了一个下午～{activity_str}，然后去{restaurant_str}。一个人也要好好过。",
            f"周末独处计划：{activity_str} + {restaurant_str}。充电放松一下。",
            f"下午的安排：{activity_str}，晚点{restaurant_str}吃饭。简简单单，舒舒服服。",
        ]
    else:
        shared = [
            f"下午安排好了！去{activity_str}，然后在{restaurant_str}吃饭。全程大概{hours}小时，轻松不累。你看看行不行？",
            f"周末计划已就绪！{start_time}出发，{activity_str} + {restaurant_str}。看看这个安排？",
        ]

    return shared


def get_share_actions(share_text: str) -> List[Dict[str, str]]:
    """返回分享操作列表。"""
    return [
        {"action": "share_to_wechat", "label": "发给微信好友", "text": share_text},
        {"action": "share_to_family_group", "label": "转发家庭群", "text": share_text},
        {"action": "copy_text", "label": "复制分享语", "text": share_text},
    ]
