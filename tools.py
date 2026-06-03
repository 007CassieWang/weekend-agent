"""
Mock API 工具函数
模拟本地生活场景的数据查询和操作
"""

import random
from typing import List, Optional, Dict, Any
from datetime import datetime
from schemas import (
    Location, Activity, Restaurant, RouteInfo,
    BookingResult, OrderResult, MessageResult
)


# ==================== POI 数据源 ====================

from poi_repository import default_poi_repository


def _activity_dicts() -> List[Dict[str, Any]]:
    return default_poi_repository.list_activity_dicts()


def _restaurant_dicts() -> List[Dict[str, Any]]:
    return default_poi_repository.list_restaurant_dicts()


# Legacy exports kept for older imports/tests. New code should use PoiRepository.
MOCK_ACTIVITIES = _activity_dicts()
MOCK_RESTAURANTS = _restaurant_dicts()


# ==================== 工具函数 ====================

def get_user_context() -> Dict[str, Any]:
    """
    获取用户默认位置、家庭信息、偏好设置

    Returns:
        用户上下文信息
    """
    return {
        "home_location": Location(
            name="幸福家园小区",
            address="市中心幸福路88号",
            coordinates={"lat": 31.2304, "lng": 121.4737},
            district="市中心"
        ),
        "family": {
            "adults": 2,
            "children": 1,
            "child_age": 5,
            "child_name": "小宝"
        },
        "preferences": {
            "diet": "low_carb",  # 减脂/低碳水
            "activity_style": "relaxed",
            "food_preference": "light_meal",
            "avoid": ["过于刺激", "过于油腻"]
        },
        "vehicle": "private_car"
    }


def search_activities(
    location: str,
    child_age: Optional[int] = None,
    duration_hours: int = 5,
    max_drive_minutes: int = 30,
    preferences: Optional[Dict[str, Any]] = None
) -> List[Activity]:
    """
    搜索附近适合的活动

    Args:
        location: 用户位置
        child_age: 儿童年龄
        duration_hours: 计划时长（小时）
        max_drive_minutes: 最大车程（分钟）
        preferences: 偏好设置

    Returns:
        符合条件的活动列表
    """
    # 将车程转换为大致距离（假设平均车速 30km/h）
    max_distance_km = (max_drive_minutes / 60) * 30

    results = []
    for activity in default_poi_repository.list_activities():
        # 距离筛选
        if activity.distance_km > max_distance_km:
            continue

        # 儿童友好筛选
        if child_age is not None and child_age < 10:
            if not activity.child_friendly:
                continue
            if activity.child_min_age and child_age < activity.child_min_age:
                continue

        # 时长筛选 - 活动时长不应超过总时长的一半
        if activity.duration_minutes > duration_hours * 60 * 0.6:
            continue

        # 室内/室外偏好过滤
        if preferences:
            style = preferences.get("activity_style", "")
            item_io = getattr(activity, "indoor_outdoor", "")
            if style == "outdoor" and item_io == "indoor":
                continue
            if style == "indoor" and item_io == "outdoor":
                continue

        # 模拟某些活动可能已满
        if random.random() < 0.1:  # 10% 概率不可预约
            activity.is_available = False

        results.append(activity)

    # 按距离排序
    results.sort(key=lambda x: x.distance_km)

    return results


def search_restaurants(
    location: str,
    people_count: int = 3,
    diet_friendly: bool = True,
    child_friendly: bool = True,
    group_friendly: bool = True,
    max_drive_minutes: int = 30,
    cuisine_keywords: Optional[List[str]] = None,
    budget_level: Optional[str] = None,
) -> List[Restaurant]:
    """
    搜索餐厅

    Args:
        location: 用户位置
        people_count: 用餐人数
        diet_friendly: 是否需要减脂友好
        child_friendly: 是否需要儿童友好
        group_friendly: 是否需要适合多人
        max_drive_minutes: 最大车程
        cuisine_keywords: 菜系关键词列表（如 ["火锅", "日料"]），用于匹配用户偏好，默认为空（不限菜系）
        budget_level: 预算等级 ("low"/"medium"/"high")，默认为 None（不限预算）

    Returns:
        符合条件的餐厅列表（按匹配度排序，高匹配在前）
    """
    max_distance_km = (max_drive_minutes / 60) * 30

    # 预算区间映射
    budget_ranges = {
        "low": (0, 100),
        "medium": (100, 300),
        "high": (300, 9999),
    }

    cuisine_keywords = cuisine_keywords or []
    budget_range = budget_ranges.get(budget_level or "") if budget_level else None

    # cuisine_keywords 归一化：支持用户说"火锅"同时匹配"火锅""重庆火锅"等
    cuisine_lower = [kw.strip().lower() for kw in cuisine_keywords if kw]

    def _cuisine_match_score(restaurant: Restaurant) -> int:
        """计算菜系匹配分：完全不匹配=0，部分匹配=1，精确匹配=3。"""
        if not cuisine_lower:
            return 0
        ct = (restaurant.cuisine_type or "").lower()
        # 拆分复合菜系（如 "粤菜/本帮菜" → ["粤菜", "本帮菜"]）
        ct_parts = [p.strip() for p in ct.replace("/", " ").split()]
        # 也检查 restaurant 的 type 字段
        rt = (restaurant.type or "").lower()
        search_text = " ".join([ct] + ct_parts + [rt])
        best = 0
        for kw in cuisine_lower:
            if kw == ct or kw in ct_parts:
                best = max(best, 3)  # 精确匹配
            elif kw in search_text:
                best = max(best, 1)  # 模糊匹配
        return best

    scored = []  # (match_score, price_penalty, restaurant)
    for restaurant in default_poi_repository.list_restaurants():
        # 距离筛选
        if restaurant.distance_km > max_distance_km:
            continue

        # 儿童友好筛选
        if child_friendly and not restaurant.child_friendly:
            continue

        # 多人筛选
        if group_friendly and not restaurant.group_friendly:
            continue

        # 预算过滤：预算等级明确时，严重超预算的餐厅大幅降权（但保留，兜底用）
        price_penalty = 0
        if budget_range:
            low, high = budget_range
            price = restaurant.price_per_person or 0
            if price > high * 1.5:
                price_penalty = 100  # 远超预算，排到最后
            elif price > high:
                price_penalty = 30   # 略超预算

        # 模拟某些餐厅可能已满
        if random.random() < 0.15:  # 15% 概率已满
            restaurant.is_available = False

        match_score = _cuisine_match_score(restaurant)
        scored.append((match_score, price_penalty, restaurant))

    # 排序：菜系匹配分降序（高分在前）→ 预算惩罚升序 → 距离升序
    scored.sort(key=lambda x: (-x[0], x[1], x[2].distance_km))

    results = [item[2] for item in scored]

    # 如果有菜系偏好且匹配数极少（≤2），日志提示
    if cuisine_lower:
        matched_count = sum(1 for item in scored if item[0] > 0)
        if matched_count <= 2:
            import logging
            logging.getLogger("tools").info(
                f"search_restaurants: 菜系关键词 {cuisine_keywords} 仅匹配 {matched_count} 家，"
                f"已返回全部 {len(results)} 家按距离兜底"
            )

    return results


def check_route_time(
    from_location: Location,
    to_location: Location,
    transportation: str = "driving"
) -> RouteInfo:
    """
    检查两个地点之间的通勤时间

    Args:
        from_location: 起点
        to_location: 终点
        transportation: 交通方式

    Returns:
        路线信息
    """
    # 简单模拟：基于直线距离计算车程时间
    # 实际应该调用地图 API

    # 模拟距离计算（实际应该用坐标计算）
    # 这里简化为从 mock 数据中获取
    distance_km = 5.0  # 默认值

    # 根据距离和交通方式计算时间
    if transportation == "driving":
        # 假设平均车速 30km/h（市区）
        travel_minutes = int((distance_km / 30) * 60)
        # 加上红绿灯等待时间
        travel_minutes += random.randint(3, 8)
    elif transportation == "public_transport":
        travel_minutes = int((distance_km / 15) * 60) + 10  # 加上换乘等待
    else:
        travel_minutes = int((distance_km / 5) * 60)  # 步行

    # 模拟交通状况
    traffic_options = ["light", "normal", "normal", "normal", "heavy"]
    traffic_condition = random.choice(traffic_options)

    if traffic_condition == "heavy":
        travel_minutes = int(travel_minutes * 1.5)
    elif traffic_condition == "light":
        travel_minutes = int(travel_minutes * 0.8)

    return RouteInfo(
        from_location=from_location,
        to_location=to_location,
        travel_minutes=max(5, travel_minutes),
        distance_km=distance_km,
        transportation=transportation,
        traffic_condition=traffic_condition
    )


def check_availability(item_id: str, item_type: str = "activity") -> Dict[str, Any]:
    """
    检查活动或餐厅是否可预约

    Args:
        item_id: 项目ID
        item_type: 类型（activity/restaurant）

    Returns:
        可用性信息
    """
    # 模拟检查
    data_source = _activity_dicts() if item_type == "activity" else _restaurant_dicts()

    item = next((x for x in data_source if x["id"] == item_id), None)
    if not item:
        return {
            "available": False,
            "message": "未找到该项目",
            "next_available": None
        }

    # 80% 概率可用
    is_available = random.random() < 0.8

    if is_available:
        return {
            "available": True,
            "message": f"{item['name']} 当前可预约",
            "next_available": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "queue_minutes": item.get("queue_minutes", 0)
        }
    else:
        return {
            "available": False,
            "message": f"{item['name']} 今日已约满",
            "next_available": "明天 10:00",
            "alternative_ids": [x["id"] for x in data_source if x["id"] != item_id][:3]
        }


def book_activity(activity: Activity, booking_time: Optional[str] = None) -> BookingResult:
    """
    Mock 预约活动

    Args:
        activity: 活动信息
        booking_time: 预约时间

    Returns:
        预约结果
    """
    # 模拟预约流程
    if not activity.reservation_available:
        return BookingResult(
            success=False,
            item_name=activity.name,
            message=f"{activity.name} 无需预约"
        )

    if not activity.is_available:
        return BookingResult(
            success=False,
            item_name=activity.name,
            message=f"{activity.name} 当前已满",
            alternative_options=["明天上午", "后天下午"]
        )

    # 模拟 90% 成功率
    if random.random() < 0.9:
        booking_id = f"BK{random.randint(10000, 99999)}"
        return BookingResult(
            success=True,
            item_name=activity.name,
            booking_id=booking_id,
            message=f"成功预约 {activity.name}，预约号：{booking_id}"
        )
    else:
        return BookingResult(
            success=False,
            item_name=activity.name,
            message=f"{activity.name} 预约失败，请稍后重试"
        )


def book_restaurant(
    restaurant: Restaurant,
    people_count: int,
    start_time: str
) -> BookingResult:
    """
    Mock 预约餐厅

    Args:
        restaurant: 餐厅信息
        people_count: 用餐人数
        start_time: 开始时间

    Returns:
        预约结果
    """
    if not restaurant.is_available:
        return BookingResult(
            success=False,
            item_name=restaurant.name,
            message=f"{restaurant.name} 当前已满座",
            alternative_options=["提前1小时", "明天同期"]
        )

    # 模拟 85% 成功率
    if random.random() < 0.85:
        booking_id = f"RT{random.randint(10000, 99999)}"
        return BookingResult(
            success=True,
            item_name=restaurant.name,
            booking_id=booking_id,
            message=f"成功预约 {restaurant.name} {people_count}人位，时间：{start_time}，预约号：{booking_id}"
        )
    else:
        return BookingResult(
            success=False,
            item_name=restaurant.name,
            message=f"{restaurant.name} 预约失败，该时段已满"
        )


def order_item(item_type: str, location: Location) -> OrderResult:
    """
    Mock 下单（蛋糕、鲜花、小礼物等）

    Args:
        item_type: 商品类型（cake/flower/gift）
        location: 取货地点

    Returns:
        订单结果
    """
    item_names = {
        "cake": "精美蛋糕",
        "flower": "鲜花束",
        "gift": "精美小礼物",
        "snack": "零食礼包"
    }

    item_name = item_names.get(item_type, "商品")

    # 模拟 95% 成功率
    if random.random() < 0.95:
        order_id = f"OD{random.randint(10000, 99999)}"
        return OrderResult(
            success=True,
            item_type=item_type,
            order_id=order_id,
            message=f"成功下单{item_name}，订单号：{order_id}，可取货地点：{location.name}"
        )
    else:
        return OrderResult(
            success=False,
            item_type=item_type,
            message=f"{item_name}下单失败，请重试"
        )


def send_plan(recipient: str, plan_summary: str) -> MessageResult:
    """
    Mock 发送方案给好友或家人

    Args:
        recipient: 接收人
        plan_summary: 方案摘要

    Returns:
        发送结果
    """
    # 模拟 98% 成功率
    if random.random() < 0.98:
        return MessageResult(
            success=True,
            recipient=recipient,
            message=f"已成功将活动方案发送给 {recipient}"
        )
    else:
        return MessageResult(
            success=False,
            recipient=recipient,
            message=f"发送给 {recipient} 失败，请检查联系方式"
        )
