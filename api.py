"""
FastAPI wrapper for the weekend activity planning agent.

The Python agent stays as the source of truth. The separate frontend calls this
API so UI work can move at normal web-app speed instead of fighting Streamlit's
generated DOM.

v2 更新:
- /api/chat 默认只生成方案 (draft)，不执行
- 新增 /api/execute 端点用于用户确认后执行 (commit)
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from agent_harness import run_agent, run_agent_plan_only
from prompts import generate_followup_questions
from orchestration import (
    generate_template_cards,
    select_card_and_lock,
    check_skip_possible,
)
from receipt import generate_receipt

# ── 安全常量 ──────────────────────────────────────────────
_MAX_MESSAGE_LENGTH = 500
_MAX_SHORT_TEXT = 200
_MAX_PLAN_ID = 100
_HTML_TAG_RE = re.compile(r"<[^>]*>", re.IGNORECASE)


def _sanitize(value: str) -> str:
    """去除 HTML 标签，防止 XSS 注入。"""
    if not value:
        return value
    return _HTML_TAG_RE.sub("", value).strip()


app = FastAPI(title="Weekend Activity Agent API")

# 服务前端静态文件（预构建的 dist）
FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

# CORS: 从环境变量读取额外的允许来源（逗号分隔），生产环境同源部署时不需要
_cors_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
_extra_origins = os.getenv("ALLOWED_ORIGINS", "").strip()
if _extra_origins:
    _cors_origins.extend(origin.strip() for origin in _extra_origins.split(",") if origin.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- In-memory session store (MVP: 单用户; 生产应换 Redis/DB) ----
_sessions: Dict[str, Any] = {}


class ChatRequest(BaseModel):
    message: str = Field(default="", min_length=1, max_length=_MAX_MESSAGE_LENGTH)
    structured_data: Optional[Dict[str, Any]] = None
    locked_constraints: Optional[Dict[str, Any]] = None  # Round 2 锁定的约束

    @field_validator("message", mode="after")
    @classmethod
    def sanitize_message(cls, v: str) -> str:
        return _sanitize(v)


class ExecuteRequest(BaseModel):
    plan_id: str = Field(min_length=1, max_length=_MAX_PLAN_ID)

    @field_validator("plan_id", mode="after")
    @classmethod
    def sanitize_plan_id(cls, v: str) -> str:
        return _sanitize(v)


class FollowupRequest(BaseModel):
    companion_context: list[str] = Field(default_factory=list)
    time_window: Optional[str] = Field(default=None, max_length=50)
    transportation: Optional[str] = Field(default=None, max_length=50)
    context_modifiers: list[str] = Field(default_factory=list)
    slot_answers: Dict[str, Any] = Field(default_factory=dict)  # 累积的槽位答案 {slot_name: value}
    location_hint: Optional[str] = Field(default=None, max_length=_MAX_MESSAGE_LENGTH)  # GUESS_CARD 地点上下文
    locked_location: Optional[str] = Field(default=None, max_length=_MAX_MESSAGE_LENGTH)  # GUESS_CARD 锁定的必含地点
    primary_intent: Optional[str] = Field(default=None, max_length=100)  # GUESS_CARD 的 primaryIntent

    @field_validator("location_hint", "locked_location", "primary_intent", mode="after")
    @classmethod
    def sanitize_optional_str(cls, v: Optional[str]) -> Optional[str]:
        return _sanitize(v) if v else v


class TemplateCardsRequest(BaseModel):
    """Round 1: 泛方案卡片生成请求"""
    group_type: str = Field(default="", max_length=50, description="同行人类型（companion_context 内部格式）")
    time_window: Optional[str] = Field(default=None, max_length=50, description="时间窗口（morning/afternoon/full_day）")
    transportation: Optional[str] = Field(default=None, max_length=50, description="交通方式（driving/transit/taxi/bike_walk）")
    selected_q_id: Optional[str] = Field(default=None, max_length=100, description="用户选择的小猜问 ID")
    user_modifications: Optional[Dict[str, Any]] = Field(default=None, description="用户修改的槽位值")
    additional_query: Optional[str] = Field(default=None, max_length=_MAX_SHORT_TEXT, description="用户附加的自然语言输入（搜索词）")

    @field_validator("additional_query", mode="after")
    @classmethod
    def sanitize_query(cls, v: Optional[str]) -> Optional[str]:
        return _sanitize(v) if v else v


class SelectCardRequest(BaseModel):
    """Round 2: 选择泛方案卡片请求"""
    card_id: str = Field(min_length=1, max_length=_MAX_PLAN_ID, description="选择的卡片 ID")
    group_type: str = Field(default="", max_length=50, description="同行人类型")
    current_slots: Dict[str, Any] = Field(default_factory=dict, description="当前已收集的槽位")
    user_additional_input: Optional[str] = Field(default=None, max_length=_MAX_SHORT_TEXT, description="用户附加输入")

    @field_validator("card_id", "user_additional_input", mode="after")
    @classmethod
    def sanitize_strings(cls, v: Optional[str]) -> Optional[str]:
        return _sanitize(v) if v else v


class ReceiptRequest(BaseModel):
    """Round 4: 小票生成请求"""
    plan_id: str = Field(min_length=1, max_length=_MAX_PLAN_ID, description="已确认的方案 ID")
    plan_data: Optional[Dict[str, Any]] = Field(default=None, description="方案完整数据")
    locked_constraints: Optional[Dict[str, Any]] = Field(default=None, description="锁定的约束条件")
    user_feedback: Optional[str] = Field(default=None, max_length=_MAX_SHORT_TEXT, description="用户反馈")

    @field_validator("plan_id", "user_feedback", mode="after")
    @classmethod
    def sanitize_strings(cls, v: Optional[str]) -> Optional[str]:
        return _sanitize(v) if v else v


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/api/chat")
def chat(payload: ChatRequest) -> Dict[str, Any]:
    """
    生成活动方案（draft 阶段）。默认只规划不执行，返回方案供前端展示。
    用户确认后调用 /api/execute 执行。

    支持 locked_constraints（来自 Round 2 选择卡片后锁定的约束），
    会注入到搜索和评分逻辑中。
    """
    user_input = payload.message.strip()

    # 如果有结构化数据，合成自然语言消息
    if payload.structured_data and not user_input:
        user_input = _synthesize_message(payload.structured_data)

    # 如果有 locked_constraints（来自 Round 2），合并到请求中
    locked = payload.locked_constraints or {}
    if payload.structured_data and payload.structured_data.get("locked_constraints"):
        locked.update(payload.structured_data.get("locked_constraints") or {})

    if not user_input and not locked:
        raise HTTPException(status_code=400, detail="请提供消息内容")

    # 如果只有 locked_constraints 没有 message，合成消息
    if not user_input and locked:
        user_input = _synthesize_from_locked_constraints(locked)

    if not user_input:
        raise HTTPException(status_code=400, detail="请提供消息内容")

    try:
        # 默认 plan_only: 只生成方案，不执行
        # 将 locked_constraints 传入 agent，使其影响搜索、补全和评分
        result = run_agent_plan_only(user_input, locked_constraints=locked)
        # 缓存 agent 实例供后续 /api/execute 使用
        # (MVP: 简单缓存; 生产应使用 agent 实例的 state)
        if result.get("plan_id"):
            _sessions[result["plan_id"]] = result
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/execute")
def execute_plan(payload: ExecuteRequest) -> Dict[str, Any]:
    """
    用户确认后执行方案（commit 阶段）。
    重新运行 agent 全流程并执行 mock 预约/下单/消息发送。
    """
    plan_id = payload.plan_id.strip()
    if not plan_id:
        raise HTTPException(status_code=400, detail="请提供方案编号")

    # 从缓存中获取原始请求文本
    cached = _sessions.get(plan_id, {})
    original_request = cached.get("request", {})

    # 用原始请求重新运行（包含执行阶段）
    user_input = original_request.get("raw_text", "")
    if not user_input:
        # fallback: 从缓存的 best_plan 重建
        best_plan = cached.get("best_plan", {})
        user_input = best_plan.get("title", "")

    if not user_input:
        raise HTTPException(status_code=400, detail="无法找到对应的原始请求")

    try:
        # full mode: 生成方案 + 执行
        result = run_agent(user_input, user_confirmed=True, execute_mode="full")
        # 清理缓存
        _sessions.pop(plan_id, None)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/suggest-followup")
def suggest_followup(payload: FollowupRequest) -> Dict[str, Any]:
    """根据已收集的结构化槽位，生成个性化猜测句。返回 completeness 用于前端判断是否需要继续追问。"""
    collected = {
        "companion_context": payload.companion_context,
        "time_window": payload.time_window,
        "transportation": payload.transportation,
        "context_modifiers": payload.context_modifiers,
        "slot_answers": payload.slot_answers,
    }
    try:
        return generate_followup_questions(
            collected,
            location_hint=payload.location_hint,
            locked_location=payload.locked_location,
            primary_intent=payload.primary_intent if hasattr(payload, 'primary_intent') else None,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/template-cards")
def template_cards(payload: TemplateCardsRequest) -> Dict[str, Any]:
    """
    Round 1: 生成三张泛方案卡片。

    用户在点击小猜问后调用，根据已识别的同行人类型和偏好生成 3 张风格卡片，
    作为最后一轮意图收敛——用户选择一张卡片后进入 Round 2 锁定约束。
    """
    if not payload.group_type:
        raise HTTPException(status_code=400, detail="请提供同行人类型")

    # 检查是否可跳步
    if payload.additional_query:
        skip_check = check_skip_possible(payload.additional_query, {})
        if skip_check.get("can_skip"):
            return {
                "round": 1,
                "output_type": "template_cards",
                "data": {
                    "skipped": True,
                    "skip_reason": skip_check.get("reason"),
                    "target_round": skip_check.get("target_round"),
                    "cards": [],
                },
                "note": "用户输入信息足够丰富，建议跳过泛方案卡片直接生成具体方案",
            }

    try:
        # 组装完整的结构化槽位信息
        structured_slots = {
            "time_window": payload.time_window,
            "transportation": payload.transportation,
        }
        result = generate_template_cards(
            group_type=payload.group_type,
            structured_slots=structured_slots,
            user_modifications=payload.user_modifications,
            additional_query=payload.additional_query,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/select-card")
def select_card(payload: SelectCardRequest) -> Dict[str, Any]:
    """
    Round 2: 用户选择泛方案卡片，锁定约束。

    合并卡片隐含约束 + 已有槽位 + 用户附加输入，返回锁定的约束条件。
    前端收到确认后应调用 /api/chat 触发具体方案生成（Round 3），
    将 locked_constraints 通过 structured_data 或 locked_constraints 字段透传。
    """
    if not payload.card_id:
        raise HTTPException(status_code=400, detail="请提供卡片编号")

    try:
        result = select_card_and_lock(
            card_id=payload.card_id,
            group_type=payload.group_type,
            current_slots=payload.current_slots,
            user_additional_input=payload.user_additional_input,
        )

        # 缓存锁定约束供后续 /api/chat 使用
        locked = result["data"].get("locked_constraints", {})
        cache_key = f"locked_{payload.card_id}"
        _sessions[cache_key] = locked

        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _synthesize_message(structured: Dict[str, Any]) -> str:
    """将结构化槽位数据合成为自然语言消息，送给 agent 解析管线。"""
    parts = []

    companion_labels = {
        "solo": "一个人", "couple": "情侣两人", "friends": "和朋友一起",
        "family_with_children": "带孩子", "family_with_elderly": "带老人",
        "colleagues": "和同事", "pet": "带宠物",
    }
    companions = structured.get("companion_context", [])
    if companions:
        labels = [companion_labels.get(c, c) for c in companions]
        parts.append("、".join(labels))

    time_labels = {
        "now": "现在就走", "morning": "上午出发", "afternoon": "下午出发",
        "full_day": "全天",
    }
    time_window = structured.get("time_window")
    if time_window:
        parts.append(time_labels.get(time_window, time_window))

    transport_labels = {
        "driving": "自驾", "transit": "坐地铁", "taxi": "打车", "bike_walk": "骑行步行",
    }
    transport = structured.get("transportation")
    if transport:
        parts.append(transport_labels.get(transport, transport))

    # 附加用户选择的追问答案
    slot_answers = structured.get("slot_answers", {})
    if slot_answers:
        answer_labels = {
            "people_count": {1: "1人", 2: "2人", "3-5": "3-5人", "6+": "6人以上", 3: "3人", 4: "4人", 5: "5人"},
            "budget_level": {"low": "人均100以内", "medium": "人均100-200", "medium_high": "人均200-300", "high": "人均300以上"},
            "child_age": {"0-3": "孩子0-3岁", "4-6": "孩子4-6岁", "7-12": "孩子7-12岁", "12+": "孩子12岁以上"},
            "cuisine_type": {"hotpot": "火锅", "japanese": "日料", "cantonese": "粤菜/本帮菜", "western": "西餐", "bbq": "烧烤", "any": "不挑食"},
            "food_preference": {"hotpot": "火锅", "japanese": "日料", "cantonese": "粤菜/本帮菜", "western": "西餐", "bbq": "烧烤", "healthy": "轻食健康餐"},
            "activity_preference": {"outdoor": "户外走走", "culture": "看展逛逛", "food": "吃顿好的", "relax": "轻松放松", "indoor": "室内娱乐"},
            "atmosphere": {"quiet": "安静一点", "lively": "热闹一点", "romantic": "浪漫一点"},
            "max_distance": {"nearby": "近一点30分钟内", "medium": "1小时内", "far": "远点也行"},
            "parent_child": {True: "需要亲子设施", False: "不需要亲子设施"},
            "parking_needed": {True: "要好停车", False: "停车无所谓"},
            "near_subway": {True: "近地铁", False: "不需要近地铁"},
            "pet_allowed": {True: "必须能带宠物", False: "宠物无所谓"},
            "low_energy": {True: "不要太累", False: "体力上没关系"},
            "photo_spot": {True: "要拍照出片", False: "拍照无所谓"},
            "quiet": {True: "要安静", False: "安静无所谓"},
            "lively": {True: "要热闹", False: "热闹无所谓"},
        }
        answer_parts = []
        for slot_name, value in slot_answers.items():
            label_map = answer_labels.get(slot_name, {})
            label = label_map.get(value, str(value))
            if label and label not in ("False", "None", "否"):
                answer_parts.append(label)
        if answer_parts:
            parts.append("偏好：" + "，".join(answer_parts))

    context_mods = structured.get("context_modifiers", [])
    if context_mods:
        mod_labels = {
            "parking_needed": "需要停车", "near_subway": "近地铁",
            "low_walking": "少走路", "photo_spot": "想拍照",
            "quiet": "安静一点", "lively": "热闹一点",
            "low_energy": "不要太累", "high_budget": "预算充足",
            "low_budget": "经济实惠",
        }
        mod_parts = [mod_labels.get(m, m) for m in context_mods if m in mod_labels]
        if mod_parts:
            parts.append("，".join(mod_parts))

    return "帮我在上海安排一个周末活动。" + "，".join(parts) + "。"


def _synthesize_from_locked_constraints(locked: Dict[str, Any]) -> str:
    """将 Round 2 锁定的约束合成为自然语言消息，用于 /api/chat 的 agent 输入。"""
    parts = ["帮我在上海安排一个周末活动。"]

    group_type = locked.get("group_type", "")
    group_labels = {
        "家庭出行": "家庭出行", "朋友聚会": "和朋友一起", "情侣约会": "情侣二人",
        "独自一人": "一个人",
    }
    if group_type:
        parts.append(group_labels.get(group_type, group_type))

    time_slot = locked.get("time_slot", "")
    time_labels = {
        "今天": "今天", "明天": "明天", "本周末": "本周末",
        "morning": "上午出发", "afternoon": "下午出发",
        "full_day": "全天活动，从上午开始", "now": "现在就走",
    }
    if time_slot:
        parts.append(time_labels.get(time_slot, time_slot))

    mobility = locked.get("mobility", "")
    mobility_labels = {"自驾": "自驾", "打车": "打车", "公共交通": "坐地铁"}
    if mobility:
        parts.append(mobility_labels.get(mobility, mobility))

    child_age = locked.get("child_age")
    if child_age:
        parts.append(f"孩子{child_age}岁")

    intent_mode = locked.get("intent_mode", "")
    intent_labels = {
        "relax": "轻松不累的", "interact": "互动参与感强的",
        "novelty": "有点新鲜特别的", "explore": "探索体验的",
        "romantic": "浪漫有氛围的", "dining": "以吃饭为主的",
    }
    if intent_mode:
        parts.append(intent_labels.get(intent_mode, ""))

    indoor_outdoor = locked.get("indoor_outdoor", "")
    if indoor_outdoor == "indoor":
        parts.append("室内活动")
    elif indoor_outdoor == "outdoor":
        parts.append("户外活动")

    activity_intensity = locked.get("activity_intensity", "")
    if activity_intensity == "low":
        parts.append("轻松低强度")
    elif activity_intensity == "medium":
        parts.append("中等强度")

    atmosphere = locked.get("atmosphere", "")
    if atmosphere == "romantic":
        parts.append("浪漫一点")
    elif atmosphere == "quiet":
        parts.append("安静一点")

    budget = locked.get("budget", "")
    budget_labels = {"low": "经济实惠", "medium": "中等预算", "high": "预算充足"}
    if budget:
        parts.append(budget_labels.get(budget, budget))

    max_travel = locked.get("max_travel_time")
    if max_travel:
        parts.append(f"车程不超过{max_travel}分钟")

    return "，".join(parts) + "。"


@app.post("/api/receipt")
def receipt(payload: ReceiptRequest) -> Dict[str, Any]:
    """
    Round 4: 生成小票卡片 + 分享语。

    用户确认具体方案后调用，返回可视化小票卡片和可转发的分享文案。
    """
    plan_data = payload.plan_data
    if not plan_data:
        # 尝试从缓存获取
        cached = _sessions.get(payload.plan_id, {})
        plan_data = cached.get("best_plan") or cached

    if not plan_data:
        raise HTTPException(status_code=400, detail="plan_data is required or plan_id must be cached")

    try:
        result = generate_receipt(
            plan=plan_data,
            locked_constraints=payload.locked_constraints,
            user_feedback=payload.user_feedback,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---- SPA fallback: 非 /api 路径优先返回静态文件，否则返回 index.html ----
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    """优先返回前端静态文件，找不到则回退到 index.html（SPA 路由）"""
    if not FRONTEND_DIST.exists():
        return {"message": "Frontend not built. Run: cd frontend && npm run build"}

    # 先尝试匹配 dist 中的静态文件（如 kangaroo.png）
    static_path = FRONTEND_DIST / full_path
    if full_path and static_path.is_file():
        return FileResponse(static_path)

    # 否则返回 index.html（SPA 客户端路由）
    index_path = FRONTEND_DIST / "index.html"
    return FileResponse(index_path)
