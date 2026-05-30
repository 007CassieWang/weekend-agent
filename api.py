"""
FastAPI wrapper for the weekend activity planning agent.

The Python agent stays as the source of truth. The separate frontend calls this
API so UI work can move at normal web-app speed instead of fighting Streamlit's
generated DOM.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agent_harness import run_agent
from prompts import generate_followup_questions


app = FastAPI(title="Weekend Activity Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str = Field(default="", max_length=500)
    structured_data: Optional[Dict[str, Any]] = None


class FollowupRequest(BaseModel):
    companion_context: list[str] = Field(default_factory=list)
    time_window: Optional[str] = None
    transportation: Optional[str] = None
    context_modifiers: list[str] = Field(default_factory=list)
    slot_answers: Dict[str, Any] = Field(default_factory=dict)  # 累积的槽位答案 {slot_name: value}


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/api/chat")
def chat(payload: ChatRequest) -> Dict[str, Any]:
    user_input = payload.message.strip()

    # 如果有结构化数据，合成自然语言消息
    if payload.structured_data and not user_input:
        user_input = _synthesize_message(payload.structured_data)

    if not user_input:
        raise HTTPException(status_code=400, detail="message is required")

    try:
        return run_agent(user_input, user_confirmed=False)
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
        return generate_followup_questions(collected)
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
