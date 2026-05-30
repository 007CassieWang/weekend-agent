"""
Streamlit mobile mock UI for the weekend activity planning agent.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any, Dict, List

import streamlit as st
import streamlit.components.v1 as components

from agent_harness import run_agent


APP_NAME = "周末行程助手"
GUESS_CARDS = [
    {
        "primary_intent": "outdoor_walk",
        "title": "自然漫步，来一场户外散心",
        "prefix": "世纪公园的",
        "highlight": "绣球花开得正盛",
        "suffix": "，这周末是花期尾巴了，想拍照的要抓紧。走走停停刚好半天，旁边吃饭也方便。",
        "chips": ["户外散心", "拍照打卡", "半天刚好"],
    },
    {
        "primary_intent": "meal",
        "title": "犒劳自己，吃顿好的",
        "prefix": "武康路新开了一家",
        "highlight": "黑珍珠粤菜馆",
        "suffix": "，上个月刚上榜，趁现在还没太火可以先去。人均200左右，周末值得。",
        "chips": ["吃顿好的", "新上榜", "适合约饭"],
    },
    {
        "primary_intent": "culture_experience",
        "title": "看展逛逛，随便晃晃",
        "prefix": "上生·新所开了",
        "highlight": "「路易斯·韦恩」猫猫插画展",
        "suffix": "，展不大但很出片，逛完旁边就是番禺路咖啡街，适合放松。",
        "chips": ["看展", "低体力", "咖啡顺路"],
    },
]


st.set_page_config(
    page_title=APP_NAME,
    page_icon="",
    layout="centered",
    initial_sidebar_state="collapsed",
)


def inject_mobile_styles() -> None:
    """Apply an iPhone-sized mobile shell on both desktop and phone widths."""
    st.markdown(
        """
        <style>
        :root {
            --phone-width: 393px;
            --phone-height: 852px;
            --app-bg: #efefed;
            --phone-bg: #fffefa;
            --ink: #111111;
            --muted: #767676;
            --line: #ececec;
            --card: #ffffff;
            --soft: #f7f7f4;
            --bubble: #f2f2ef;
            --input-shell: #fffefa;
            --input-bg: #fffefa;
            --intro-bg: #f6f6f2;
            --intro-ink: #3c3c38;
        }

        html, body, [data-testid="stAppViewContainer"] {
            background: var(--app-bg);
            color-scheme: light;
        }

        [data-testid="stHeader"],
        [data-testid="stToolbar"],
        [data-testid="stDecoration"],
        [data-testid="stSidebar"],
        footer {
            display: none !important;
        }

        [data-testid="stAppViewContainer"] > .main {
            display: flex;
            justify-content: center;
            min-height: 100vh;
        }

        [data-testid="stMainBlockContainer"] {
            width: min(var(--phone-width), 100vw) !important;
            max-width: var(--phone-width) !important;
            height: min(var(--phone-height), calc(100vh - 48px));
            max-height: var(--phone-height);
            padding: 0 18px 92px !important;
            background: var(--phone-bg);
            box-shadow: 0 24px 70px rgba(0, 0, 0, 0.12);
            position: relative;
            overflow: hidden;
        }

        @media (min-width: 460px) {
            [data-testid="stMainBlockContainer"] {
                margin: 24px 0;
                border-radius: 42px;
                overflow: hidden;
            }
        }

        .block-container p {
            margin-bottom: 0;
        }

        div[data-testid="stVerticalBlock"] {
            gap: 0;
        }

        .phone-status {
            height: 54px;
            display: flex;
            align-items: end;
            justify-content: space-between;
            padding: 0 16px 8px;
            color: var(--ink);
            font-size: 15px;
            font-weight: 700;
            letter-spacing: 0;
        }

        .status-icons {
            display: flex;
            align-items: center;
            gap: 5px;
            font-size: 14px;
        }

        .signal {
            display: inline-flex;
            align-items: end;
            gap: 2px;
            height: 14px;
        }

        .signal i {
            display: block;
            width: 3px;
            background: #111;
            border-radius: 2px;
        }

        .signal i:nth-child(1) { height: 5px; }
        .signal i:nth-child(2) { height: 8px; }
        .signal i:nth-child(3) { height: 11px; }
        .signal i:nth-child(4) { height: 14px; }

        .battery {
            width: 24px;
            height: 12px;
            border: 2px solid #111;
            border-radius: 5px;
            position: relative;
            box-sizing: border-box;
        }

        .battery:before {
            content: "";
            position: absolute;
            right: -4px;
            top: 3px;
            width: 2px;
            height: 4px;
            background: #111;
            border-radius: 0 2px 2px 0;
        }

        .battery:after {
            content: "";
            position: absolute;
            left: 2px;
            top: 2px;
            width: 14px;
            height: 4px;
            background: #111;
            border-radius: 2px;
        }

        .phone-nav {
            height: 72px;
            display: grid;
            grid-template-columns: 44px 1fr 44px;
            align-items: center;
            padding: 0 12px;
            color: var(--ink);
        }

        .nav-icon {
            width: 34px;
            height: 34px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: var(--ink);
            font-size: 28px;
            line-height: 1;
        }

        .compose-icon {
            color: #b9b9b4;
            font-size: 25px;
            transform: rotate(-2deg);
        }

        .app-title {
            text-align: center;
            font-size: 24px;
            font-weight: 760;
            letter-spacing: 0;
            white-space: nowrap;
        }

        .app-title span {
            color: #9b9b95;
            font-weight: 500;
            margin-left: 4px;
        }

        .chat-space {
            height: calc(min(var(--phone-height), calc(100vh - 48px)) - 54px - 72px - 106px);
            overflow-y: auto;
            overscroll-behavior: contain;
            padding: 10px 0 22px;
            scrollbar-width: thin;
        }

        .empty-state {
            min-height: 100%;
            display: flex;
            flex-direction: column;
            justify-content: flex-end;
            gap: 10px;
            color: var(--muted);
            padding: 0 6px 32px;
        }

        .empty-title {
            color: var(--ink);
            font-size: 24px;
            line-height: 1.2;
            font-weight: 760;
            letter-spacing: 0;
        }

        .empty-copy {
            font-size: 14px;
            line-height: 1.55;
        }

        .suggestions {
            display: flex;
            flex-direction: column;
            gap: 10px;
            margin-top: 10px;
        }

        .suggestion {
            border: 1px solid var(--line);
            background: var(--card);
            border-radius: 18px;
            padding: 12px;
            color: var(--ink);
            font-size: 13px;
            line-height: 1.35;
            box-shadow: 0 5px 16px rgba(20, 20, 20, 0.04);
        }

        .suggestion-title {
            color: var(--ink);
            font-size: 15px;
            line-height: 1.25;
            font-weight: 760;
            margin-bottom: 6px;
        }

        .suggestion-copy {
            color: #555550;
            font-size: 12px;
            line-height: 1.45;
        }

        .suggestion-copy strong {
            color: var(--ink);
            font-weight: 760;
        }

        .suggestion-chips {
            display: flex;
            flex-wrap: wrap;
            gap: 5px;
            margin-top: 9px;
        }

        .suggestion-chips span {
            border-radius: 999px;
            background: #f4f4f1;
            border: 1px solid #e8e8e4;
            color: #5f5f59;
            padding: 4px 8px;
            font-size: 11px;
            line-height: 1;
        }

        .message {
            margin: 10px 0;
            display: flex;
        }

        .message.user {
            justify-content: flex-end;
        }

        .message.agent {
            justify-content: flex-start;
        }

        .bubble {
            max-width: 86%;
            border-radius: 20px;
            padding: 12px 14px;
            font-size: 15px;
            line-height: 1.48;
            word-break: break-word;
        }

        .user .bubble {
            background: #111111;
            color: white;
            border-bottom-right-radius: 7px;
        }

        .agent .bubble {
            background: var(--bubble);
            color: var(--ink);
            border-bottom-left-radius: 7px;
        }

        .plan-card {
            margin: 12px 0 18px;
            background: var(--card);
            border: 1px solid var(--line);
            border-radius: 22px;
            padding: 16px;
            box-shadow: 0 10px 30px rgba(20, 20, 20, 0.06);
        }

        .card-intro {
            color: var(--intro-ink);
            background: var(--intro-bg);
            border-radius: 16px;
            padding: 11px 12px;
            font-size: 14px;
            line-height: 1.45;
            margin-bottom: 14px;
        }

        .card-label {
            color: var(--muted);
            font-size: 12px;
            line-height: 1.1;
            margin-bottom: 7px;
        }

        .card-title {
            color: var(--ink);
            font-size: 19px;
            line-height: 1.25;
            font-weight: 760;
            letter-spacing: 0;
            margin-bottom: 12px;
        }

        .meta-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
            margin-bottom: 14px;
        }

        .meta-box {
            border-radius: 14px;
            background: var(--soft);
            padding: 10px;
            min-height: 58px;
        }

        .meta-k {
            color: var(--muted);
            font-size: 11px;
            margin-bottom: 5px;
        }

        .meta-v {
            color: var(--ink);
            font-size: 15px;
            font-weight: 720;
            line-height: 1.2;
        }

        .section-title {
            color: var(--ink);
            font-size: 14px;
            font-weight: 760;
            margin: 14px 0 8px;
        }

        .timeline {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .timeline-row {
            display: grid;
            grid-template-columns: 74px 1fr;
            gap: 10px;
            padding: 10px 0;
            border-top: 1px solid var(--line);
        }

        .timeline-time {
            color: var(--muted);
            font-size: 12px;
            line-height: 1.25;
        }

        .timeline-main {
            min-width: 0;
        }

        .timeline-activity {
            color: var(--ink);
            font-size: 14px;
            font-weight: 680;
            line-height: 1.3;
        }

        .timeline-place {
            color: var(--muted);
            font-size: 12px;
            line-height: 1.3;
            margin-top: 3px;
        }

        .chips {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin-top: 8px;
        }

        .chip {
            border-radius: 999px;
            background: #f4f4f1;
            color: #4d4d49;
            border: 1px solid #e8e8e4;
            padding: 5px 9px;
            font-size: 12px;
            line-height: 1.1;
        }

        .risk {
            color: #6f4c00;
            background: #fff7df;
            border: 1px solid #f2e4b8;
            border-radius: 14px;
            padding: 10px;
            font-size: 13px;
            line-height: 1.45;
            margin-top: 10px;
        }

        .mock-note {
            color: var(--muted);
            font-size: 11px;
            line-height: 1.35;
            text-align: center;
            padding: 6px 16px 0;
        }

        div[class*="st-key-mobile-input-bar"] {
            position: absolute;
            left: 24px;
            right: 24px;
            bottom: 18px;
            z-index: 20;
            width: auto !important;
            max-width: calc(100% - 48px) !important;
            border: 1px solid #e9e9e4;
            border-radius: 30px;
            background: var(--input-shell);
            box-shadow: 0 14px 38px rgba(0, 0, 0, 0.12);
            padding: 10px 62px 10px 18px !important;
            margin: 0 !important;
            min-height: 64px;
            box-sizing: border-box;
            overflow: hidden;
        }

        div[class*="st-key-mobile-input-bar"] div[data-testid="stVerticalBlock"] {
            gap: 0 !important;
            display: block !important;
            position: static !important;
        }

        div[class*="st-key-mobile-input-bar"] div[data-testid="stElementContainer"]:has(div[data-testid="stTextInput"]) {
            width: 100% !important;
            margin: 0 !important;
            padding: 0 !important;
        }

        div[class*="st-key-mobile-input-bar"] div[data-testid="stElementContainer"]:has(div[data-testid="stButton"]) {
            position: absolute !important;
            right: 12px !important;
            top: 50% !important;
            transform: translateY(-50%) !important;
            width: 42px !important;
            height: 42px !important;
            min-width: 42px !important;
            margin: 0 !important;
            padding: 0 !important;
            z-index: 2;
        }

        div[class*="st-key-mobile-input-bar"] div[data-testid="stTextInput"] {
            width: 100% !important;
            margin: 0 !important;
        }

        div[class*="st-key-mobile-input-bar"] div[data-testid="stButton"] {
            position: static !important;
            width: 42px !important;
            height: 42px !important;
            min-width: 42px !important;
        }

        div[class*="st-key-mobile-input-bar"] div[data-baseweb="input"] {
            border: none !important;
            background: var(--input-bg) !important;
            border-radius: 0 !important;
            min-height: 42px !important;
            box-shadow: none !important;
            outline: none !important;
        }

        div[class*="st-key-mobile-input-bar"] div[data-baseweb="input"] *,
        div[class*="st-key-mobile-input-bar"] div[data-baseweb="base-input"] {
            background: var(--input-bg) !important;
            border: none !important;
            outline: none !important;
        }

        div[class*="st-key-mobile-input-bar"] input {
            color: var(--ink) !important;
            font-size: 16px !important;
            line-height: 1.2 !important;
            background: var(--input-bg) !important;
            caret-color: var(--ink) !important;
            -webkit-text-fill-color: var(--ink) !important;
            box-shadow: 0 0 0 1000px var(--input-bg) inset !important;
            border: none !important;
            outline: none !important;
        }

        div[class*="st-key-mobile-input-bar"] input::placeholder {
            color: #8f929b !important;
            opacity: 1 !important;
        }

        div[class*="st-key-mobile-input-bar"] button {
            width: 42px !important;
            height: 42px !important;
            min-height: 42px !important;
            padding: 0 !important;
            border: none !important;
            border-radius: 14px !important;
            background: #eceff3 !important;
            color: #8f929b !important;
            font-size: 25px !important;
            line-height: 1 !important;
            box-shadow: none !important;
        }

        div[class*="st-key-mobile-input-bar"] button p {
            font-size: 25px !important;
            line-height: 1 !important;
            margin: 0 !important;
        }

        @media (max-width: 430px) {
            [data-testid="stMainBlockContainer"] {
                width: 100vw !important;
                max-width: 100vw !important;
                height: 100vh;
                max-height: 100vh;
                box-shadow: none;
                padding-left: 18px !important;
                padding-right: 18px !important;
            }

            .chat-space {
                height: calc(100vh - 54px - 72px - 106px);
            }
        }

        </style>
        """,
        unsafe_allow_html=True,
    )


def render_phone_header() -> None:
    now = datetime.now().strftime("%H:%M")
    st.markdown(
        f"""
        <div class="phone-status">
            <div>{escape(now)}</div>
            <div class="status-icons">
                <span class="signal"><i></i><i></i><i></i><i></i></span>
                <span>5G</span>
                <span class="battery"></span>
            </div>
        </div>
        <div class="phone-nav">
            <div class="nav-icon">≡</div>
            <div class="app-title">{APP_NAME}<span>›</span></div>
            <div class="nav-icon compose-icon">⌕</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def run_agent_for_chat(user_input: str) -> Dict[str, Any]:
    """Run the existing agent in plan-only mode for the chat UI."""
    return run_agent(user_input, user_confirmed=False)


def get_duration_text(plan: Dict[str, Any]) -> str:
    minutes = int(plan.get("total_duration_minutes") or 0)
    if minutes <= 0:
        return "-"
    hours = minutes // 60
    rest = minutes % 60
    if hours and rest:
        return f"{hours}小时{rest}分"
    if hours:
        return f"{hours}小时"
    return f"{rest}分钟"


def compact_labels(values: List[str], limit: int = 5) -> List[str]:
    cleaned = [value for value in values if value and value != "unknown"]
    return cleaned[:limit]


LABEL_TEXT = {
    "solo": "独自",
    "couple": "情侣/伴侣",
    "family_with_children": "亲子同行",
    "family_with_elderly": "带长辈",
    "friends": "朋友同行",
    "colleagues": "同事同行",
    "pet": "带宠物",
    "meal": "吃饭",
    "cafe_tea": "咖啡茶饮",
    "culture_experience": "文化体验",
    "indoor_entertainment": "室内娱乐",
    "outdoor_walk": "户外散步",
    "shopping_mall": "商场综合体",
    "wellness_relax": "放松疗愈",
    "nightlife": "夜间活动",
    "parent_child": "亲子活动",
    "short_trip": "周边短途",
    "time_killing": "打发时间",
    "mixed_plan": "组合安排",
    "rainy_day": "雨天",
    "low_budget": "低预算",
    "low_energy": "低体力",
    "quiet": "安静",
    "lively": "热闹",
    "photo_spot": "拍照打卡",
    "no_reservation": "免预约优先",
    "parking_needed": "需要停车",
    "near_subway": "近地铁",
    "low_walking": "少步行",
    "queue_sensitive": "少排队",
    "child_safety": "儿童安全",
    "elder_mobility": "长辈友好",
    "pet_allowed": "宠物可入",
    "max_distance": "距离优先",
    "budget_cap": "预算封顶",
    "time_window": "时间窗口",
}


def label_text(value: str) -> str:
    return LABEL_TEXT.get(value, value)


def render_chip_list(values: List[str]) -> str:
    chips = compact_labels(values)
    if not chips:
        return ""
    return "<div class='chips'>" + "".join(
        f"<span class='chip'>{escape(label_text(value))}</span>" for value in chips
    ) + "</div>"


def build_agent_card_html(result: Dict[str, Any]) -> str:
    if not result.get("success"):
        return (
            "<div class='plan-card'>"
            "<div class='card-label'>生成失败</div>"
            f"<div class='card-intro'>这次没有生成可用方案：{escape(result.get('error', '未知错误'))}</div>"
            "</div>"
        )

    request = result.get("request", {})
    plan = result.get("best_plan", {})
    restaurant = plan.get("restaurant") or {}
    activities = plan.get("activities") or []
    timeline = plan.get("timeline") or []
    risks = plan.get("risks") or []

    companion = ", ".join(label_text(value) for value in compact_labels(request.get("companion_context", []))) or "未指定"
    intent = label_text(request.get("primary_intent") or "-")
    score = float(plan.get("score") or 0)
    food_text = restaurant.get("name") or "按需补充"
    first_activity = activities[0]["name"] if activities else "轻量活动"
    title = plan.get("title") or "推荐行程"

    rows = []
    for item in timeline[:7]:
        rows.append(
            "<div class='timeline-row'>"
            f"<div class='timeline-time'>{escape(item.get('time', '-'))}</div>"
            "<div class='timeline-main'>"
            f"<div class='timeline-activity'>{escape(item.get('activity', '-'))}</div>"
            f"<div class='timeline-place'>{escape(item.get('location', '-'))}</div>"
            "</div>"
            "</div>"
        )

    chips_html = render_chip_list(
        (request.get("context_modifiers") or [])
        + (request.get("hard_constraints") or [])
        + (request.get("soft_preferences") or [])
    )
    risk_html = ""
    if risks:
        risk_html = f"<div class='risk'>{escape('；'.join(risks[:3]))}</div>"

    reason = plan.get("recommendation_reason") or "按你的时间、预算、距离和偏好综合排序。"

    return (
        "<div class='plan-card'>"
        "<div class='card-label'>推荐方案</div>"
        "<div class='card-intro'>我按你的需求整理了一个可执行方案，可以直接按下面的时间线走。</div>"
        f"<div class='card-title'>{escape(title)}</div>"
        "<div class='meta-grid'>"
        "<div class='meta-box'>"
        "<div class='meta-k'>同行场景</div>"
        f"<div class='meta-v'>{escape(companion)}</div>"
        "</div>"
        "<div class='meta-box'>"
        "<div class='meta-k'>主要意图</div>"
        f"<div class='meta-v'>{escape(intent)}</div>"
        "</div>"
        "<div class='meta-box'>"
        "<div class='meta-k'>预计时长</div>"
        f"<div class='meta-v'>{escape(get_duration_text(plan))}</div>"
        "</div>"
        "<div class='meta-box'>"
        "<div class='meta-k'>匹配分</div>"
        f"<div class='meta-v'>{score:.1f}</div>"
        "</div>"
        "</div>"
        "<div class='section-title'>核心安排</div>"
        "<div class='meta-grid'>"
        "<div class='meta-box'>"
        "<div class='meta-k'>活动</div>"
        f"<div class='meta-v'>{escape(first_activity)}</div>"
        "</div>"
        "<div class='meta-box'>"
        "<div class='meta-k'>餐饮</div>"
        f"<div class='meta-v'>{escape(food_text)}</div>"
        "</div>"
        "</div>"
        "<div class='section-title'>时间线</div>"
        f"<div class='timeline'>{''.join(rows)}</div>"
        f"{chips_html}"
        f"{risk_html}"
        f"<div class='risk'>{escape(reason)}</div>"
        "</div>"
    )


def build_empty_state_html() -> str:
    suggestions = "".join(
        (
            "<div class='suggestion'>"
            f"<div class='suggestion-title'>{escape(card['title'])}</div>"
            "<div class='suggestion-copy'>"
            f"{escape(card['prefix'])}<strong>{escape(card['highlight'])}</strong>{escape(card['suffix'])}"
            "</div>"
            "<div class='suggestion-chips'>"
            + "".join(f"<span>{escape(chip)}</span>" for chip in card["chips"])
            + "</div>"
            "</div>"
        )
        for card in GUESS_CARDS
    )
    return (
        "<div class='empty-state'>"
        "<div class='empty-title'>你想怎么安排这段空闲时间？</div>"
        "<div class='empty-copy'>告诉我时间、地点、同行人、预算或偏好。我会用中国本地生活场景给你返回一张可执行行程卡片。</div>"
        f"<div class='suggestions'>{suggestions}</div>"
        "</div>"
    )


def render_chat_history() -> None:
    messages = st.session_state.get("messages", [])
    html_parts = ["<div class='chat-space' id='phone-chat-scroll'>"]
    if not messages:
        html_parts.append(build_empty_state_html())
        html_parts.append("</div>")
        st.markdown("".join(html_parts), unsafe_allow_html=True)
        return

    for message in messages:
        if message["role"] == "user":
            html_parts.append(
                "<div class='message user'>"
                f"<div class='bubble'>{escape(message['content'])}</div>"
                "</div>"
            )
        else:
            html_parts.append(build_agent_card_html(message["result"]))
    html_parts.append("</div>")
    st.markdown("".join(html_parts), unsafe_allow_html=True)


def render_input_bar() -> str:
    with st.container(key="mobile-input-bar"):
        user_input = st.text_input(
            "消息",
            placeholder="消息",
            label_visibility="collapsed",
            key="mobile_message_text",
        )
        submitted = st.button("↑", key="mobile_send", use_container_width=True)

    if submitted and user_input.strip():
        return user_input.strip()
    return ""


def scroll_to_phone_top_if_needed() -> None:
    if not st.session_state.pop("scroll_to_phone_top", False):
        return
    components.html(
        """
        <script>
        const doc = window.parent.document;
        const chat = doc.querySelector('#phone-chat-scroll');
        if (chat) {
          chat.scrollTo({ top: 0, left: 0, behavior: "instant" });
        }
        </script>
        """,
        height=0,
    )


def main() -> None:
    inject_mobile_styles()

    if "messages" not in st.session_state:
        st.session_state.messages = []

    render_phone_header()
    render_chat_history()

    user_input = render_input_bar()
    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.spinner("正在规划..."):
            result = run_agent_for_chat(user_input)
        st.session_state.messages.append({"role": "agent", "result": result})
        st.session_state.scroll_to_phone_top = True
        st.rerun()

    scroll_to_phone_top_if_needed()


if __name__ == "__main__":
    main()
