"""
提示词模板和 mock_llm 解析规则
支持从 product_rules.yaml 读取配置，并可选接入 DeepSeek LLM 提升解析准确率。

v2 更新: 增加 LLM token 用量追踪上报。
"""

import os
import json
import yaml
import random
import re
import logging
from functools import lru_cache
from typing import Dict, Any, Optional, List
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("weekend_agent.prompts")

# ==================== 规则加载 ====================

@lru_cache(maxsize=1)
def load_product_rules() -> Dict[str, Any]:
    """加载产品规则配置（结果缓存，避免重复磁盘读取和 YAML 解析）。"""
    try:
        with open("config/product_rules.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return {
            "product_profile": {
                "target_user": "本地短时活动规划用户",
                "default_scenario": "本地短时活动规划"
            },
            "defaults": {
                "start_time": "14:00",
                "duration_hours": 4,
                "max_drive_minutes": 30,
                "budget_level": "medium"
            },
            "clarification_rules": {
                "default_when_missing": {
                    "exact_start_time": "14:00",
                    "duration_hours": 4,
                    "budget_level": "medium",
                    "max_drive_minutes": 30,
                    "companions": "unknown",
                    "child_age": None,
                    "diet_goal": "none"
                }
            },
            "scoring_weights": {
                "time_fit": 20,
                "distance_fit": 20,
                "group_fit": 15,
                "availability_risk": 10
            }
        }


# ==================== 工具函数 ====================

def _has_any(text: str, keywords: List[str]) -> bool:
    return any(keyword.lower() in text for keyword in keywords)


def _dedupe(values: List[str]) -> List[str]:
    return list(dict.fromkeys(value for value in values if value))


# ==================== 统一入口 ====================

def parse_request(user_input: str) -> Dict[str, Any]:
    """
    统一的需求解析入口。
    根据 product_rules.yaml 的 llm_config 决定走 LLM 还是 mock。
    """
    rules = load_product_rules()
    llm_cfg = rules.get("llm_config", {})
    parser_cfg = llm_cfg.get("parser", {})

    if parser_cfg.get("enabled", False):
        try:
            result = parse_request_llm(user_input, rules, llm_cfg)
            _ensure_transportation_context_modifiers(result)
            return result
        except Exception as e:
            if parser_cfg.get("fallback_to_mock", True):
                result = parse_request_mock(user_input)
                result["parser"] = "mock_fallback"
                result["parse_error"] = str(e)
                return result
            raise

    return parse_request_mock(user_input)


def _ensure_transportation_context_modifiers(result: Dict[str, Any]) -> None:
    """确保 transportation 核心槽位被正确映射到 context_modifiers。

    当 transportation 已设置但 context_modifiers 中缺少对应的派生标签时自动补充。
    避免 LLM/自由文本路径下遗漏通勤方式对行程规划的影响。
    """
    transport = result.get("transportation")
    if not transport:
        return
    transport_mod_map = {
        "driving": "parking_needed",
        "transit": "near_subway",
        "bike_walk": "low_walking",
    }
    auto_mod = transport_mod_map.get(transport)
    if not auto_mod:
        return
    modifiers = result.get("context_modifiers", [])
    if not isinstance(modifiers, list):
        modifiers = []
    if auto_mod not in modifiers:
        modifiers.insert(0, auto_mod)
        result["context_modifiers"] = modifiers


# ==================== LLM 解析 ====================

@lru_cache(maxsize=1)
def _build_llm_system_prompt() -> str:
    """从 product_rules.yaml 构建 LLM system prompt（结果缓存，运行时仅构建一次）。"""
    rules = load_product_rules()
    detection = rules.get("scenario_detection", {})
    output_schema = detection.get("output_schema", {})
    slot_schema = rules.get("slot_schema", {})
    defaults = rules.get("defaults", {})

    companion_ctx = output_schema.get("companion_context", {})
    relation_ctx = output_schema.get("relation_context", {})
    primary_intent = output_schema.get("primary_intent", {})
    context_mod = output_schema.get("context_modifiers", {})
    hard_const = output_schema.get("hard_constraints", {})
    soft_pref = output_schema.get("soft_preferences", {})

    return f"""你是一个中国本地生活短时活动规划助手。你的任务是将用户的自然语言输入解析为结构化 JSON。

## 输出字段说明

### 时间相关
- time_window: 时间窗口描述 (如 "today_afternoon", "tonight", "tomorrow", "weekend")，无法确定时填 null
- start_time: 开始时间 HH:MM 格式，无法确定时填 null
- duration_hours: 活动时长(小时)，无法确定时填 null

### 人员相关
- people_count: 总人数(整数)，无法确定时填 null
- companions: 同行人类型，取值: "family_with_kids" / "family_with_elderly" / "family_mixed" / "friends" / "couple" / "solo"，无法确定时填 null
- child_age: 儿童年龄(整数)，没有儿童填 null
- has_child: 是否带儿童 (true/false)
- has_elderly: 是否有老人 (true/false)

### 位置相关
- location: 出发地点，无法确定时填 null
- distance_preference: 距离偏好 "nearby" / "far"，无法确定时填 null
- max_drive_minutes: 最大车程(分钟)，无法确定时填 null

### 通勤方式（核心槽位，优先级低于同行人、时间窗口和时长）
- transportation: 通勤方式，取值: "driving"（自驾）/ "transit"（地铁公交）/ "taxi"（打车）/ "bike_walk"（骑行步行）
  影响后续 max_drive_minutes 解读、路线规划、停车/地铁偏好
  当用户说"开车""自驾"时填 "driving"；"地铁""公交"时填 "transit"；"打车""叫车"时填 "taxi"；"骑车""步行""附近走走"时填 "bike_walk"
  无法确定时填 null，不要臆测

### 偏好相关
- budget_level: 预算等级 "low" / "medium" / "high"，默认 "medium"
- activity_preference: 活动偏好，如 "relax" / "art" / "outdoor" / "entertainment" / "food" / "celebration"，无法确定时填 null
- food_preference: 餐饮偏好，如 "healthy" / "spicy" / "western" / "chinese"，无法确定时填 null
- diet_goal: 饮食目标，如 "health_diet"（减脂/低卡/控糖/低碳），没有填 "none"

### 多标签场景分类
- companion_context: 同行人上下文标签列表
  可选值: {json.dumps(companion_ctx.get('allowed_values', []), ensure_ascii=False)}
  可多选。例如同时有孩子和配偶：["family_with_children", "couple"]
- relation_context: 关系上下文列表
  可选值: {json.dumps(relation_ctx.get('allowed_values', []), ensure_ascii=False)}
  当识别到"老婆""老公"等配偶关系时填入 "spouse"。可多选。
- primary_intent: 主要意图（单选）
  可选值: {json.dumps(primary_intent.get('allowed_values', []), ensure_ascii=False)}
- context_modifiers: 上下文修饰标签列表（可多选）
  可选值: {json.dumps(context_mod.get('allowed_values', []), ensure_ascii=False)}
- hard_constraints: 硬约束标签列表（可多选）
  可选值: {json.dumps(hard_const.get('allowed_values', []), ensure_ascii=False)}
- soft_preferences: 软偏好标签列表（可多选）
  可选值: {json.dumps(soft_pref.get('allowed_values', []), ensure_ascii=False)}

### 派生字段
- scenario_type: 场景类型
  取值: "family_with_children" / "elderly_friendly" / "couple_date" / "friends_social" / "solo_relax" / "pet_friendly" / "health_diet" / "active_outdoor" / "culture_experience" / "general_leisure"
  根据 companion_context 和 primary_intent 综合判断
- scoring_profile: 评分模板名称，与 scenario_type 相同
- activated_constraints: 根据 hard_constraints + 场景类型推断的需要激活的约束列表

### 追问判断
- should_ask: 需要追问的缺失信息列表（仅列出影响方案可执行性的关键项）
- should_not_assume: 不应预设的信息列表，如 ["children", "elderly", "pet", "diet_goal", "accessibility_need"]，当用户明确提及时从列表中移除
- missing_slots: 缺失的槽位列表

### 元信息
- confidence: 整体置信度 (0-1)

## 关键规则

1. **不要臆测**：用户没明确说的信息设为 null，不要预设。尤其是儿童、老人、宠物、减脂、无障碍——除非用户明确提到
2. **区分配偶和孩子**："老婆孩子" / "妻儿" → companion_context 包含 ["family_with_children"]，relation_context 包含 ["spouse"]，scenario_type = "family_with_children"；单独的"老婆"/"老公" → companion_context 包含 ["couple"]，relation_context 包含 ["spouse"]，scenario_type = "couple_date"
3. **否定处理**：用户说"不带孩子""不带宠物"时，不要激活对应标签
4. **默认值**：起始时间默认 14:00，时长默认 4 小时，预算默认 medium，车程默认 30 分钟
5. **输出格式**：严格 JSON，不要包含 markdown 代码块标记，直接输出纯 JSON
"""


# ---- Token 用量追踪 ----

def _try_record_usage(response: Any, model: str = "deepseek-chat") -> None:
    """尝试从 OpenAI-compatible response 中提取用量并记录到日志。
    不抛出异常，失败时静默跳过。"""
    try:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        total_tokens = getattr(usage, "total_tokens", 0) or prompt_tokens + completion_tokens

        # DeepSeek 公开价格 (RMB / 1K tokens)
        pricing = {"deepseek-chat": (0.001, 0.002), "deepseek-reasoner": (0.004, 0.016)}
        input_price, output_price = pricing.get(model, (0.001, 0.002))
        cost = (prompt_tokens / 1000) * input_price + (completion_tokens / 1000) * output_price

        logger.info(
            "llm_usage model=%s prompt_tokens=%d completion_tokens=%d total_tokens=%d cost_rmb=%.6f",
            model, prompt_tokens, completion_tokens, total_tokens, cost,
        )
    except Exception:
        pass  # 用量追踪不应影响主流程


def parse_request_llm(
    user_input: str,
    rules: Optional[Dict[str, Any]] = None,
    llm_cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    使用 DeepSeek LLM 解析用户请求。

    Args:
        user_input: 用户输入的自然语言
        rules: 产品规则（可选，不传则自动加载）
        llm_cfg: LLM 配置（可选，不传则从 rules 中取）

    Returns:
        与 parse_request_mock 格式完全一致的结构化 dict
    """
    import openai

    rules = rules or load_product_rules()
    llm_cfg = llm_cfg or rules.get("llm_config", {})

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY 环境变量未设置")

    client = openai.OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com/v1",
    )

    model = llm_cfg.get("parser", {}).get("model", "deepseek-chat")
    temperature = llm_cfg.get("temperature", 0.1)
    max_tokens = llm_cfg.get("max_tokens", 2000)
    timeout = llm_cfg.get("timeout_seconds", 8)

    system_prompt = _build_llm_system_prompt()

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        response_format={"type": "json_object"},
    )

    _try_record_usage(response, model)

    raw_text = response.choices[0].message.content.strip()

    # 清理可能的 markdown 代码块标记
    if raw_text.startswith("```"):
        lines = raw_text.split("\n")
        # 去掉首行 ```json 和末行 ```
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw_text = "\n".join(lines)

    parsed = json.loads(raw_text)
    parsed["parser"] = "deepseek"
    return parsed


def generate_followup_questions(
    collected_slots: Dict[str, Any],
    location_hint: Optional[str] = None,
    locked_location: Optional[str] = None,
    primary_intent: Optional[str] = None,
) -> Dict[str, Any]:
    """
    根据用户已选择的结构化槽位，生成个性化猜测句。

    猜测句是包含具体槽位值的自然语言短句（如"人均预算100-200""孩子5岁左右"），
    用户点击后滑入对话框作为 query 发送，可编辑。

    Args:
        collected_slots: 包含 companion_context, time_window, transportation, context_modifiers 的字典
        location_hint: GUESS_CARD 地点上下文（如"世纪公园绣球花，适合拍照"）
        locked_location: GUESS_CARD 锁定的必含地点名
        primary_intent: GUESS_CARD 的 primaryIntent

    Returns:
        {"sentences": [{"text": "...", "slots": [{"name": "...", "value": "..."}]}, ...],
         "completeness": 0.0-1.0}  // completeness 表示槽位完整度，>=0.7 建议生成方案
    """
    import openai

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        sentences = _generate_guess_sentences_mock(collected_slots, location_hint)
        return {
            "sentences": sentences,
            "completeness": _estimate_completeness(collected_slots, sentences),
        }

    companion_labels = {
        "solo": "独自出行", "couple": "情侣出行", "friends": "朋友出行",
        "family_with_children": "家庭出行(带娃)", "family_with_elderly": "带老人",
        "colleagues": "同事出行", "pet": "带宠物",
    }
    time_labels = {
        "now": "现在就走", "morning": "上午", "afternoon": "下午",
        "full_day": "全天",
    }
    transport_labels = {
        "driving": "自驾", "transit": "地铁/公交", "taxi": "打车", "bike_walk": "骑行/步行",
    }

    companion_cn = ", ".join(companion_labels.get(c, c) for c in (collected_slots.get("companion_context") or []))
    time_cn = time_labels.get(collected_slots.get("time_window", ""), collected_slots.get("time_window", "未指定"))
    transport_cn = transport_labels.get(collected_slots.get("transportation", ""), collected_slots.get("transportation", "未指定"))

    # 地点上下文（来自 GUESS_CARD）
    location_context = ""
    if location_hint or locked_location:
        loc_name = locked_location or location_hint.split("，")[0].split(",")[0]
        location_context = f"""
【重要】用户已从推荐卡片选择了具体目的地：{loc_name}（{location_hint or ''}）
你生成的每句猜测句都应围绕用户在 {loc_name} 的行程展开，但不要反复出现地名——句子内容与目的地相关即可，用自然的方式细化需求（如拍照时段、体力要求、餐饮偏好、预算等），不必每句都塞进地名。
【关键】猜测句是陈述句，不是疑问句！不要用"吗""呢""好不好""怎么样"结尾，不要用问号。用户点击后会作为信息补充，不是在回答问题。
正确示例（陈述句，给信息让用户选）：
- "下午光线好，拍照很出片"
- "逛完在附近找家粤菜"
- "地铁直达，不需要开车"
- "半天刚好，不赶时间"
先给1-2句围绕目的地场景的细化信息（陈述句），再补充1句通用槽位（人数/预算/交通）。地名最多在1句中自然出现。"""

    system_prompt = f"""你是一个中国本地生活规划助手的猜测模块。用户已经通过结构化表单提供了以下信息：

- 和谁一起：{companion_cn}
- 时间偏好：{time_cn}
- 交通方式：{transport_cn}
{location_context}

你的任务是根据这些已收集的信息，推测用户可能还有哪些未明确的需求，生成 2-3 句猜测句。用户点击猜测句后会滑入对话框作为 query 发送，AI 根据这些信息生成方案。

## 猜测句格式要求

每句话是一句自然口语化的中文短句，**包含具体的猜测槽位值**。不要用问号，不要用"？"结尾。像朋友帮你拿主意一样说。

正确示例：
- "带孩子去亲子友好的户外活动" （同时覆盖 child_age、activity_preference、parent_child）
- "人均预算100-200" （覆盖 budget_level）
- "想吃粤菜" （覆盖 cuisine_type/food_preference）
- "找个拍照出片的地方" （覆盖 photo_spot）
- "孩子5岁左右" （覆盖 child_age）
- "安静一点的环境" （覆盖 quiet/atmosphere）
- "开车去，要好停车" （覆盖 parking_needed）
- "近地铁方便" （覆盖 near_subway）
- "3-4个人" （覆盖 people_count）
- "不太累，轻松为主" （覆盖 low_energy）
- "可以接受远一点的地方" （覆盖 max_distance）

错误示例（不要这样写）：
- "孩子多大了？" ← 这是提问，不是猜测，而且有问号
- "想吃啥？" ← 同上
- "拍照吗？" ← 同上

## 推测规则

1. **根据同行人推测**：
   - 独自出行 → 推测活动偏好（放松/探索）、预算中等、喜欢安静
   - 情侣出行 → 推测氛围浪漫、拍照出片、预算中高
   - 朋友出行 → 推测人数3-5人、热闹、火锅/烧烤
   - 家庭带娃 → 推测孩子年龄4-6岁、亲子设施、粤菜/清淡
   - 带老人 → 推测少走路、安静环境、户外散步
   - 同事出行 → 推测人数4-6人、预算中等、粤菜/火锅
   - 带宠物 → 推测宠物友好、户外活动

2. **根据时间推测**：
   - 现在就走/上午 → 推测距离近、半天活动
   - 下午 → 推测下午茶/活动为主
   - 全天 → 推测全天活动、可以远一些

3. **根据交通推测**：
   - 自驾 → 推测好停车、可以去远一点
   - 地铁/公交 → 推测近地铁
   - 打车 → 推测中等距离
   - 骑行/步行 → 推测附近、不要太累

4. **核心原则**：
   - 每句话 5-15 字，简洁口语化
   - 必须包含具体可感知的值（如"100-200"、"粤菜"、"5岁"、"出片"），而不是抽象提问
   - 不要问号
   - 不要问已经知道的信息
   - 2-3 句即可，选择最可能影响方案质量的槽位去猜

## 输出格式

严格 JSON：
{{"sentences": [{{"text": "猜测句文案", "slots": [{{"name": "槽位名", "value": "槽位值"}}]}}]}}

每个 sentence 的 slots 数组列出该句覆盖的槽位，slot name 必须使用以下值之一：
people_count, budget_level, child_age, cuisine_type, food_preference, activity_preference, atmosphere, max_distance, parent_child, parking_needed, near_subway, pet_allowed, low_energy, photo_spot, quiet, lively, high_budget, low_budget

slot value 是对应槽位的具体值，如 budget_level 的值可以是 "low"/"medium"/"medium_high"/"high"，people_count 的值可以是 2/3/4 等数字。"""

    try:
        client = openai.OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com/v1",
        )

        if location_hint and locked_location:
            user_msg = f"目的地={locked_location}（{location_hint}），和谁={companion_cn}，时间={time_cn}，交通={transport_cn}。请围绕{locked_location}生成2-3句陈述式猜测句（不要疑问句，不要问号）。句子应细化与目的地相关的需求（拍照时段、体力、餐饮偏好、预算等），不要每句都硬塞地名——目的地作为上下文而非每句的主角。"
        else:
            user_msg = f"已收集信息：和谁={companion_cn}，时间={time_cn}，交通={transport_cn}。请生成2-3句陈述式个性化猜测句（不要疑问句，不要问号）。"

        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.7,
            max_tokens=600,
            timeout=10,
            response_format={"type": "json_object"},
        )

        _try_record_usage(response, "deepseek-chat")

        raw_text = response.choices[0].message.content.strip()
        if raw_text.startswith("```"):
            lines = raw_text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw_text = "\n".join(lines)

        result = json.loads(raw_text)
        result["completeness"] = _estimate_completeness(collected_slots, result.get("sentences", []))
        return result
    except Exception:
        result = {"sentences": _generate_guess_sentences_mock(collected_slots)}
        result["completeness"] = _estimate_completeness(collected_slots, result.get("sentences", []))
        return result


def generate_creative_title(locations: List[str], scene_type: str, vibe: str = "", group_detail: str = "") -> str:
    """
    调用 DeepSeek 生成有画面感和节奏感的出行方案创意标题。

    Args:
        locations: 地点名称列表（活动名 + 餐厅名）
        scene_type: 场景类型 (family / friends / couple / solo)
        vibe: 氛围关键词，如"户外放松""文化体验""美食探店"
        group_detail: 同行人详情，如"孩子5岁、老婆减肥""4人聚会"

    Returns:
        创意标题字符串，20字以内。LLM 不可用时返回基于规则的兜底标题。
    """
    scene_cn = {"family": "家庭出行", "friends": "朋友聚会", "couple": "情侣约会", "solo": "独自出行"}.get(scene_type, "出行")
    loc_str = "、".join(locations[:5]) if locations else "本地"
    vibe_str = vibe or "放松"

    system_prompt = f"""你是一个出行方案标题生成器。根据用户出行的地点列表、场景类型和同行人信息，生成一个主题句式的主标题。

规则：
1. 禁止罗列地名。标题中最多出现1个地名作为锚点，其余地点用体验词、节奏词、氛围词替代
2. 标题必须体现整段旅程的节奏变化或反差感，用"→"或"从…到…"串联不同阶段
3. 标题要让没看过方案的人也能感受到这趟出行的氛围，而不是读行程单
4. 长度控制在20字以内
5. 全天多地点方案：捕捉地点间的体验反差，用时间跨度、感官跳跃或情绪转折制造张力
6. 单地点方案：用地点+独特体验氛围组合，给平凡场景找到不平凡的切入点
7. 风格要求：有画面感、有节奏感、略带诗意但不矫情，像一个会写文案的朋友随口说的那种

好标题的标准：读完想发朋友圈，而不是读完知道去了哪。

示例：
- 从恐龙到微醺：一场穿越3亿年的周末
- 从画布到酒杯：今天只负责好看
- 去森林里撒个野，风会帮你带娃
- 不用出城的微度假，一个商场就够了
- 湖风胡同烤鸭香：北京该有的样子
- 先动手玩再坐下来吃，科学也很有味道

输出纯文本，不要 JSON，不要引号包裹，不要换行，不要任何前缀或解释。只要标题本身。"""

    user_prompt = f"地点：{loc_str} | {scene_cn} | {group_detail or ''} | 氛围：{vibe_str}"

    try:
        import openai
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY 环境变量未设置")

        client = openai.OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com/v1",
        )

        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.9,
            max_tokens=80,
            timeout=8,
        )

        _try_record_usage(response, "deepseek-chat")
        title = response.choices[0].message.content.strip()
        # 清理可能的引号
        title = title.strip('"').strip("'").strip("「").strip("」").strip("《").strip("》")
        if len(title) > 25:
            title = title[:24] + "…"
        return title if title else _fallback_creative_title(locations, scene_type, group_detail)

    except Exception:
        return _fallback_creative_title(locations, scene_type, group_detail)


def _fallback_creative_title(locations: List[str], scene_type: str, group_detail: str = "") -> str:
    """LLM 不可用时的规则兜底标题。"""
    scene_prefix = {
        "family": "遛娃",
        "friends": "聚会",
        "couple": "约会",
        "solo": "独处",
    }.get(scene_type, "出行")

    if len(locations) >= 3:
        return f"从{locations[0][:3]}到{locations[-1][:3]}：一场{scene_prefix}慢行"
    elif len(locations) == 2:
        return f"{locations[0][:4]} + {locations[1][:4]}：{scene_prefix}刚刚好"
    elif len(locations) == 1:
        return f"在{locations[0][:6]}，给{scene_prefix}一个下午"
    else:
        return f"一场{scene_prefix}，随性出发"


def _estimate_completeness(collected_slots: Dict[str, Any], sentences: list) -> float:
    """估算槽位完整度。0.0-1.0，>=0.7 建议生成方案。"""
    covered = set()

    # Q1 已收集的视为已覆盖
    companion = collected_slots.get("companion_context") or []
    if companion:
        covered.add("companion_context")
    if collected_slots.get("time_window"):
        covered.add("time_window")
    if collected_slots.get("transportation"):
        covered.add("transportation")

    # transportation 是核心槽位，影响后续所有规划
    # 缺失时 registered_required_slots 会加入 transportation，自然地通过 completeness 机制降低评分

    # 根据同行人类型判断还需要哪些关键槽位
    key_slots_by_companion = {
        "solo": ["activity_preference", "budget_level"],
        "couple": ["atmosphere", "budget_level", "food_preference"],
        "friends": ["people_count", "cuisine_type", "budget_level"],
        "family_with_children": ["child_age", "food_preference", "parent_child"],
        "family_with_elderly": ["low_energy", "quiet", "activity_preference"],
        "colleagues": ["people_count", "budget_level", "cuisine_type"],
        "pet": ["pet_allowed", "activity_preference"],
    }

    required_slots = set()
    for c in companion:
        required_slots.update(key_slots_by_companion.get(c, ["budget_level", "food_preference"]))

    if not required_slots:
        required_slots = {"transportation", "budget_level", "food_preference", "activity_preference"}

    # transportation 是核心槽位，未收集时降低完整度
    if not collected_slots.get("transportation"):
        required_slots.add("transportation")

    # 从已有槽位答案和猜测句中提取已覆盖的槽位
    existing_answers = collected_slots.get("slot_answers", {})
    covered.update(existing_answers.keys())

    for s in sentences:
        for slot in (s.get("slots") or []):
            covered.add(slot.get("name", ""))

    intersection = required_slots & covered
    return min(len(intersection) / max(len(required_slots), 1), 1.0)


def _generate_guess_sentences_mock(collected_slots: Dict[str, Any], location_hint: Optional[str] = None) -> list:
    """Mock fallback: generate guess sentences with concrete slot values."""
    companion = (collected_slots.get("companion_context") or [])[:1]
    companion = companion[0] if companion else "unknown"
    transport = collected_slots.get("transportation", "")

    templates = {
        "solo": [
            {"text": "一个人轻松逛逛", "slots": [{"name": "activity_preference", "value": "relax"}, {"name": "low_energy", "value": True}]},
            {"text": "人均预算100-200", "slots": [{"name": "budget_level", "value": "medium"}]},
            {"text": "安静舒服的环境", "slots": [{"name": "quiet", "value": True}]},
        ],
        "couple": [
            {"text": "氛围浪漫一点", "slots": [{"name": "atmosphere", "value": "romantic"}]},
            {"text": "找个拍照出片的地方", "slots": [{"name": "photo_spot", "value": True}]},
            {"text": "人均预算200-300", "slots": [{"name": "budget_level", "value": "medium_high"}]},
        ],
        "friends": [
            {"text": "3-4个人一起", "slots": [{"name": "people_count", "value": 3}]},
            {"text": "热闹有氛围的", "slots": [{"name": "lively", "value": True}]},
            {"text": "吃火锅", "slots": [{"name": "cuisine_type", "value": "hotpot"}]},
        ],
        "family_with_children": [
            {"text": "孩子4-6岁", "slots": [{"name": "child_age", "value": "4-6"}]},
            {"text": "需要亲子设施", "slots": [{"name": "parent_child", "value": True}]},
            {"text": "不要太累的", "slots": [{"name": "low_energy", "value": True}]},
        ],
        "family_with_elderly": [
            {"text": "少走路，轻松为主", "slots": [{"name": "low_energy", "value": True}]},
            {"text": "安静舒服的环境", "slots": [{"name": "quiet", "value": True}]},
            {"text": "户外散步类型", "slots": [{"name": "activity_preference", "value": "outdoor"}]},
        ],
        "colleagues": [
            {"text": "4-6个人", "slots": [{"name": "people_count", "value": 4}]},
            {"text": "人均预算100-200", "slots": [{"name": "budget_level", "value": "medium"}]},
            {"text": "吃粤菜或火锅", "slots": [{"name": "cuisine_type", "value": "cantonese"}]},
        ],
        "pet": [
            {"text": "必须宠物友好", "slots": [{"name": "pet_allowed", "value": True}]},
            {"text": "户外活动为主", "slots": [{"name": "activity_preference", "value": "outdoor"}]},
        ],
        "unknown": [
            {"text": "人均预算100-200", "slots": [{"name": "budget_level", "value": "medium"}]},
            {"text": "轻松不累的活动", "slots": [{"name": "low_energy", "value": True}]},
            {"text": "找个拍照出片的地方", "slots": [{"name": "photo_spot", "value": True}]},
        ],
    }

    sentences = list(templates.get(companion, templates["unknown"]))

    # 地点感知：GUESS_CARD 有锁定地点时，优先生成地点相关猜问（但不反复出现地名）
    if location_hint:
        loc_name = location_hint.split("，")[0].split(",")[0] if location_hint else ""
        location_sentences = [
            {"text": f"在{loc_name}待半天，不赶时间", "slots": [{"name": "activity_preference", "value": "relax"}, {"name": "low_energy", "value": True}]},
            {"text": "逛完在附近找家餐厅", "slots": [{"name": "food_preference", "value": "casual"}]},
            {"text": "不用预约，说走就走", "slots": [{"name": "no_reservation", "value": True}]},
        ]
        sentences = location_sentences[:2] + sentences

    # 根据交通方式补充
    if transport == "driving":
        sentences.append({"text": "开车去，要好停车", "slots": [{"name": "parking_needed", "value": True}]})
    elif transport == "transit":
        sentences.append({"text": "近地铁方便", "slots": [{"name": "near_subway", "value": True}]})

    return sentences[:5]


# ==================== Mock 规则解析（保留作为 fallback） ====================

def classify_scenario_labels(user_input: str, rules: Optional[Dict[str, Any]] = None, transportation: Optional[str] = None) -> Dict[str, Any]:
    """多标签场景识别。

    只根据用户明确表达或强语义命中激活儿童、老人、宠物、减脂、无障碍等约束。
    transportation 为核心槽位，传入后会据此自动派生 context_modifiers（如 driving → parking_needed）。
    """
    rules = rules or load_product_rules()
    text = user_input.lower()

    child_terms = ["孩子", "小孩", "宝宝", "亲子", "儿童", "娃", "儿子", "女儿", "幼儿园", "一家三口", "老婆孩子"]
    elder_terms = ["父母", "爸妈", "老人", "长辈", "爷爷", "奶奶", "外公", "外婆", "老人家"]
    pet_terms = ["宠物", "带狗", "带猫", "遛狗", "猫咪", "狗狗", "可带宠", "宠物友好"]
    spouse_terms = ["老婆", "老公", "妻子", "丈夫", "爱人", "另一半"]

    has_child = _has_any(text, child_terms)
    has_elder = _has_any(text, elder_terms)
    pet_negated = _has_any(text, ["不带宠物", "不带狗", "不带猫", "没宠物", "没有宠物", "不带狗狗", "不带猫咪"])
    has_pet = _has_any(text, pet_terms) and not pet_negated
    has_spouse = _has_any(text, spouse_terms)

    companion_context: List[str] = []
    relation_context: List[str] = []
    if _has_any(text, ["一个人", "自己", "独处", "单独", "独自"]):
        companion_context.append("solo")
    friend_context = _has_any(text, ["朋友", "好友", "哥们", "闺蜜", "兄弟", "同学", "搭子"])
    if _has_any(text, ["女朋友", "男朋友"]) and not _has_any(text, ["和朋友", "朋友们", "几个朋友", "朋友一起"]):
        friend_context = False
    if friend_context:
        companion_context.append("friends")
    if _has_any(text, ["同事", "团队", "部门", "客户"]):
        companion_context.append("colleagues")
    if has_child:
        companion_context.append("family_with_children")
    if has_elder:
        companion_context.append("family_with_elderly")
    if has_pet:
        companion_context.append("pet")
    if _has_any(text, ["情侣", "约会", "女朋友", "男朋友", "对象", "二人世界"]) and not has_child:
        companion_context.append("couple")
    if has_spouse:
        relation_context.append("spouse")
        if not has_child and not has_elder and "couple" not in companion_context:
            companion_context.append("couple")
    if not companion_context:
        companion_context.append("unknown")

    primary_intent = "mixed_plan"
    intent_keywords = [
        ("parent_child", ["亲子", "儿童乐园", "儿童剧", "孩子玩", "带娃", "科技馆"]),
        ("meal", ["吃饭", "吃个", "想吃", "晚饭", "餐厅", "美食", "火锅", "烧烤", "日料", "西餐", "夜宵", "粤菜", "本帮菜"]),
        ("cafe_tea", ["咖啡", "茶馆", "奶茶", "下午茶", "甜品"]),
        ("culture_experience", ["展览", "看展", "博物馆", "美术馆", "艺术", "演出", "音乐剧", "livehouse", "市集", "手作"]),
        ("indoor_entertainment", ["电影院", "电影", "ktv", "剧本杀", "密室", "桌游", "台球", "保龄球", "电玩城"]),
        ("outdoor_walk", ["公园", "散步", "走走", "citywalk", "城市漫步", "骑行", "徒步", "露营", "滨水"]),
        ("shopping_mall", ["商场", "购物中心", "奥莱", "商业街", "步行街", "逛街"]),
        ("wellness_relax", ["spa", "按摩", "洗浴", "温泉", "瑜伽", "放松", "疗愈", "书店"]),
        ("nightlife", ["夜生活", "酒吧", "夜店", "livehouse", "深夜", "晚上嗨"]),
        ("short_trip", ["周边游", "短途", "郊区", "一日游", "半日游"]),
        ("time_killing", ["打发时间", "消磨时间", "待一会", "待两小时", "杀时间"]),
    ]
    matched_intents = [intent for intent, kws in intent_keywords if _has_any(text, kws)]
    if _has_any(text, ["不吃饭", "不用吃饭", "不安排吃饭"]) and "meal" in matched_intents:
        matched_intents.remove("meal")
    if len(matched_intents) == 1:
        primary_intent = matched_intents[0]
    elif len(matched_intents) > 1:
        meal_or_cafe = {"meal", "cafe_tea"}
        if set(matched_intents).issubset(meal_or_cafe):
            primary_intent = matched_intents[0]
        else:
            primary_intent = "mixed_plan"

    if primary_intent == "mixed_plan" and has_child and _has_any(text, ["玩", "安排", "活动"]):
        primary_intent = "parent_child"

    context_modifiers: List[str] = []
    modifier_keywords = {
        "rainy_day": ["下雨", "雨天", "阴雨"],
        "hot_weather": ["太热", "高温", "热天", "暴晒"],
        "cold_weather": ["太冷", "降温", "冷天"],
        "low_budget": ["便宜", "省钱", "低预算", "预算不高", "实惠", "人均100", "人均 100", "100以内", "不要太贵", "别太贵", "别太高", "不用太贵", "不太贵"],
        "high_budget": ["高端", "贵一点", "预算充足", "精致", "仪式感"],
        "low_energy": ["别太累", "不要太累", "不想太累", "不累", "低体力", "轻松", "少走路", "懒得动"],
        "high_energy": ["运动", "爬山", "徒步", "骑行", "出汗", "高强度"],
        "quiet": ["安静", "清静", "人少", "不吵"],
        "lively": ["热闹", "气氛好", "嗨", "好玩"],
        "photo_spot": ["拍照", "出片", "打卡", "好看"],
        "no_reservation": ["不想预约", "不用预约", "免预约", "说走就走"],
        "parking_needed": ["开车", "停车", "好停车", "自驾"],
        "near_subway": ["地铁", "近地铁", "地铁口"],
        "low_walking": ["少走路", "不想走", "走不动", "低步行"],
        "queue_sensitive": ["不想排队", "不要排队", "少排队", "别排队", "等位少"],
    }
    for modifier, kws in modifier_keywords.items():
        if _has_any(text, kws):
            context_modifiers.append(modifier)
    if has_elder:
        context_modifiers.extend(["low_walking", "quiet"])

    # 通勤方式自动派生 context_modifiers（核心槽位，避免重复从关键词检测）
    if transportation:
        transport_mod_map = {
            "driving": "parking_needed",
            "transit": "near_subway",
            "bike_walk": "low_walking",
        }
        auto_mod = transport_mod_map.get(transportation)
        if auto_mod and auto_mod not in context_modifiers:
            context_modifiers.insert(0, auto_mod)

    hard_constraints: List[str] = []
    if has_child:
        hard_constraints.append("child_safety")
    if has_elder:
        hard_constraints.append("elder_mobility")
    if has_pet:
        hard_constraints.append("pet_allowed")
    if _has_any(text, ["过敏"]) and re.search(r'(花生|坚果|海鲜|牛奶|乳糖|蛋|鸡蛋|麸质|芒果|酒精).*过敏|过敏.*(花生|坚果|海鲜|牛奶|乳糖|蛋|鸡蛋|麸质|芒果|酒精)', text):
        hard_constraints.append("allergy_safe")
    if _has_any(text, ["无障碍", "轮椅", "行动不便", "拐杖"]):
        hard_constraints.append("accessibility")
        if "low_walking" not in context_modifiers:
            context_modifiers.append("low_walking")
    if _has_any(text, ["不要太远", "别太远", "不远", "附近", "离家近", "30分钟内", "半小时内"]):
        hard_constraints.append("max_distance")
    if _has_any(text, ["预算不超过", "不能超过", "封顶", "人均100", "100以内"]) or re.search(r'(人均)?\s*\d+\s*以内', text):
        hard_constraints.append("budget_cap")
    if _has_any(text, ["两小时", "2小时", "半天", "下午", "晚上", "今晚", "周日", "周六", "周末"]):
        hard_constraints.append("time_window")

    soft_preferences: List[str] = []
    if _has_any(text, ["安静", "热闹", "浪漫", "氛围", "舒服", "仪式感"]):
        soft_preferences.append("atmosphere")
    if _has_any(text, ["特别", "新鲜", "小众", "不一样", "特色"]):
        soft_preferences.append("uniqueness")
    if _has_any(text, ["聊天", "聚会", "互动", "一起玩"]):
        soft_preferences.append("social_interaction")
    if _has_any(text, ["服务好", "少踩雷"]):
        soft_preferences.append("service_quality")
    if _has_any(text, ["好吃", "美食", "餐厅", "口味"]):
        soft_preferences.append("food_quality")
    if _has_any(text, ["环境好", "场地好", "体验好", "设施"]):
        soft_preferences.append("place_quality")
    if _has_any(text, ["团购", "优惠", "券", "折扣", "划算"]):
        soft_preferences.append("coupon_or_discount")
    if _has_any(text, ["顺路", "路线", "少折腾", "动线"]):
        soft_preferences.append("route_smoothness")
    if has_elder:
        soft_preferences.extend(["route_smoothness", "place_quality", "atmosphere"])

    should_ask = []
    if has_child and not re.search(r'\d+\s*岁', user_input):
        should_ask.append("child_age_optional")
    if not _has_any(text, ["上海", "北京", "广州", "深圳", "杭州", "成都", "附近", "家附近", "公司附近", "离家"]):
        should_ask.append("location")
    if "unknown" in companion_context and not re.search(r'\d+\s*个?人', user_input):
        should_ask.append("people_count")

    should_not_assume = ["spouse", "children", "elderly", "pet", "diet_goal", "accessibility_need"]
    if has_spouse:
        should_not_assume.remove("spouse")
    if has_child:
        should_not_assume.remove("children")
    if has_elder:
        should_not_assume.remove("elderly")
    if has_pet:
        should_not_assume.remove("pet")
    has_explicit_diet_goal = _has_any(text, ["减肥", "减脂", "低卡", "控糖", "低碳", "健康餐"])
    if has_explicit_diet_goal:
        should_not_assume.remove("diet_goal")
    if "accessibility" in hard_constraints:
        should_not_assume.remove("accessibility_need")

    style = "中国本地生活语境，给出商圈/POI类型、时间线、交通和预约排队风险"

    return {
        "companion_context": _dedupe(companion_context),
        "relation_context": _dedupe(relation_context),
        "primary_intent": primary_intent,
        "context_modifiers": _dedupe(context_modifiers),
        "hard_constraints": _dedupe(hard_constraints),
        "soft_preferences": _dedupe(soft_preferences),
        "should_ask": _dedupe(should_ask),
        "should_not_assume": _dedupe(should_not_assume),
        "recommendation_style": style,
    }


def detect_scenario_type(user_input: str, rules: Optional[Dict[str, Any]] = None, transportation: Optional[str] = None) -> Dict[str, Any]:
    """根据多标签结果派生旧版 scenario_type，保证 demo 兼容。"""
    rules = rules or load_product_rules()
    detection = rules.get("scenario_detection", {})
    scenarios = detection.get("scenarios", {})
    default_type = detection.get("default_scenario_type", "general_leisure")
    labels = classify_scenario_labels(user_input, rules, transportation=transportation)
    companion_context = set(labels["companion_context"])
    hard_constraints = set(labels["hard_constraints"])
    primary_intent = labels["primary_intent"]

    if "family_with_children" in companion_context or "child_safety" in hard_constraints:
        best_type = "family_with_children"
    elif "family_with_elderly" in companion_context:
        best_type = "elderly_friendly"
    elif "pet" in companion_context or "pet_allowed" in hard_constraints:
        best_type = "pet_friendly"
    elif "couple" in companion_context:
        best_type = "couple_date"
    elif "friends" in companion_context or "colleagues" in companion_context:
        best_type = "friends_social"
    elif "solo" in companion_context:
        best_type = "solo_relax"
    elif any(term in user_input.lower() for term in ["减肥", "减脂", "低卡", "控糖", "低碳", "健康餐"]):
        best_type = "health_diet"
    elif primary_intent == "culture_experience":
        best_type = "culture_experience"
    elif primary_intent == "outdoor_walk":
        best_type = "active_outdoor"
    else:
        best_type = default_type

    scenario = scenarios.get(best_type, scenarios.get(default_type, {}))
    activated_constraints = list(scenario.get("activated_constraints", []))
    activated_constraints.extend(labels["hard_constraints"])
    return {
        "scenario_type": best_type,
        "scenario_labels": labels,
        "activated_constraints": _dedupe(activated_constraints),
        "scoring_profile": scenario.get("scoring_profile", "general"),
    }


def get_system_prompt() -> str:
    """
    获取系统提示词
    """
    rules = load_product_rules()
    user_profile = rules.get("product_profile", rules.get("user_profile", {}))

    return f"""你是 [周末闲时活动规划助手]，专门帮助用户规划本地短时活动。

【产品定位】
{user_profile.get('product_positioning', '帮助用户快速规划本地活动')}

【目标用户】
{user_profile.get('target_user', '本地短时活动规划用户')}

【核心能力】
1. 理解用户的自然语言需求，提取关键约束（时间、人数、偏好等）
2. 根据约束条件搜索合适的活动和餐厅
3. 生成完整的活动方案，包括时间线、路线、预约安排
4. 执行预约、下单、通知等操作

【处理原则】
- 如果用户未明确出发时间，默认使用 14:00
- 如果用户未明确活动时长，默认使用配置中的中性时长
- 如果用户未明确预算，默认中等消费
- 如果用户未明确位置，默认使用配置中的默认出发点
- 不预设用户有孩子、家庭同行或减脂需求
- 先识别场景，再启用儿童、健康饮食、宠物、老人等可选约束

【输出格式】
请以 JSON 格式输出解析结果，包含以下字段：
- time_window: 时间窗口描述
- start_time: 开始时间（HH:MM 格式）
- duration_hours: 活动时长（小时）
- people_count: 总人数
- companions: 同行人类型（family/friends/couple/solo）
- child_age: 儿童年龄
- has_child: 是否带儿童
- location: 出发地点
- distance_preference: 距离偏好
- budget_level: 预算等级（low/medium/high）
- activity_preference: 活动偏好
- food_preference: 餐饮偏好
- scenario_type: 场景类型
- activated_constraints: 激活约束
- scoring_profile: 评分模板
- execution_intent: 执行意图
"""


def parse_request_mock(user_input: str) -> Dict[str, Any]:
    """
    Mock LLM 解析用户请求
    使用规则匹配模拟 LLM 的解析能力

    Args:
        user_input: 用户输入的自然语言

    Returns:
        解析后的结构化数据
    """
    rules = load_product_rules()
    defaults = rules.get("defaults", {})
    clarification = rules.get("clarification_rules", {})
    default_when_missing = clarification.get("default_when_missing", {})

    # 转换为小写便于匹配
    text = user_input.lower()

    # 初始化结果
    result = {
        "raw_text": user_input,
        "time_window": None,
        "start_time": None,
        "duration_hours": None,
        "people_count": None,
        "companions": None,
        "child_age": None,
        "has_child": False,
        "has_elderly": False,
        "location": None,
        "distance_preference": None,
        "transportation": None,
        "budget_level": None,
        "activity_preference": None,
        "food_preference": None,
        "diet_goal": "none",
        "scenario_type": "general_leisure",
        "activated_constraints": [],
        "scoring_profile": "general",
        "scenario_labels": {},
        "execution_intent": "plan_then_confirm",
        "missing_slots": [],
    }

    # ===== 解析通勤方式（核心槽位，优先级最高）=====
    transport_rules = {
        "driving": ["自驾", "开车", "自己开", "自己开车"],
        "transit": ["地铁", "公交", "坐地铁", "公共交通", "搭地铁"],
        "taxi": ["打车", "叫车", "网约车", "滴滴", "出租车"],
        "bike_walk": ["骑车", "骑行", "自行车", "步行", "走路", "走过去", "单车", "共享单车"],
    }
    for mode, keywords in transport_rules.items():
        if _has_any(text, keywords):
            result["transportation"] = mode
            break

    # ===== 解析时间 =====
    # 今天/下午/晚上
    if "今天" in user_input or "下午" in user_input:
        result["time_window"] = "today_afternoon"
        result["start_time"] = "14:00"
    elif "晚上" in user_input:
        result["time_window"] = "tonight"
        result["start_time"] = "18:00"
    elif "明天" in user_input:
        result["time_window"] = "tomorrow"
        result["start_time"] = "14:00"
    elif "周末" in user_input:
        result["time_window"] = "weekend"
        result["start_time"] = "14:00"

    # 时长
    if "几个小时" in user_input or "几小时" in user_input:
        result["duration_hours"] = defaults.get("duration_hours", 4)
    elif re.search(r'(\d+)\s*个?小时', user_input):
        match = re.search(r'(\d+)\s*个?小时', user_input)
        result["duration_hours"] = int(match.group(1))
    elif "半天" in user_input:
        result["duration_hours"] = defaults.get("duration_hours", 4)
    elif "一天" in user_input:
        result["duration_hours"] = 8

    # ===== 解析人员 - 更精细的用户画像分类 =====

    # 检测是否有老人关键词
    has_elderly = any(kw in text for kw in ["爸妈", "父母", "老人", "爷爷奶奶", "外公外婆", "长辈", "老人家"])
    # 检测是否有儿童关键词
    has_child = any(kw in text for kw in ["孩子", "儿童", "宝宝", "小孩", "娃", "儿子", "女儿", "宝贝"])

    # 带老人的家庭（无儿童）
    if has_elderly and not has_child:
        result["companions"] = "family_with_elderly"
        result["has_elderly"] = True
        result["has_child"] = False
        result["people_count"] = 3  # 自己+父母2人
    # 既有老人又有儿童
    elif has_elderly and has_child:
        result["companions"] = "family_mixed"
        result["has_elderly"] = True
        result["has_child"] = True
        result["people_count"] = 5  # 自己+父母2人+孩子
    # 带儿童的家庭（无老人）
    elif any(kw in text for kw in ["老婆孩子", "妻儿", "老婆", "老公", "妻子", "丈夫"]) and has_child:
        result["companions"] = "family_with_kids"
        result["has_child"] = True
        result["people_count"] = 3
    # 仅儿童（可能只有孩子没提配偶）
    elif has_child:
        result["companions"] = "family_with_kids"
        result["has_child"] = True
        result["people_count"] = 2
    # 朋友
    elif any(kw in text for kw in ["朋友", "好友", "哥们", "闺蜜", "兄弟", "大家", "一块", "一起"]):
        result["companions"] = "friends"
        result["people_count"] = 4
    # 情侣/夫妻（无儿童无老人）
    elif any(kw in text for kw in ["女朋友", "男朋友", "情侣", "约会", "两口子", "二人世界"]):
        result["companions"] = "couple"
        result["people_count"] = 2
    # 独自
    elif any(kw in text for kw in ["自己", "一个人", "单独", "独自", "个人", "散心"]):
        result["companions"] = "solo"
        result["people_count"] = 1

    # 提取具体人数
    match = re.search(r'(\d+)\s*个?人', user_input)
    if match:
        result["people_count"] = int(match.group(1))

    # 提取儿童年龄
    match = re.search(r'(\d+)\s*岁', user_input)
    if match:
        result["child_age"] = int(match.group(1))
        result["has_child"] = True
        # 如果明确有儿童年龄但 companions 还没确定，设为带儿童家庭
        if not result["companions"]:
            result["companions"] = "family_with_kids"

    # ===== 兜底：如果还没识别出 companions，检查是否有默认线索 =====
    if not result["companions"]:
        # 检查是否有夫妻/配偶但没有儿童老人
        if any(kw in text for kw in ["老婆", "老公", "妻子", "丈夫", "全家", "家人", "家里"]):
            result["companions"] = "couple"
            result["people_count"] = result["people_count"] or 2

    # ===== 解析距离偏好 =====
    if any(kw in text for kw in ["不远", "附近", "离家近", "别太远", "近一点"]):
        result["distance_preference"] = "nearby"
    elif any(kw in text for kw in ["远点", "远一些", "出去", "外面"]):
        result["distance_preference"] = "far"

    # ===== 解析预算 =====
    if any(kw in text for kw in ["便宜", "省钱", "经济", "实惠", "划算"]):
        result["budget_level"] = "low"
    elif any(kw in text for kw in ["贵", "高端", "奢侈", "豪华", "高档"]):
        result["budget_level"] = "high"
    else:
        result["budget_level"] = "medium"

    # ===== 解析活动偏好 =====
    # 优先级从高到低检查
    if any(kw in text for kw in ["生日", "庆祝", "聚会", "party"]):
        result["activity_preference"] = "celebration"
    elif any(kw in text for kw in ["别太累", "不要太累", "不累", "轻松", "少走路"]):
        result["activity_preference"] = "relax"
    elif any(kw in text for kw in ["展", "艺术", "博物馆", "画廊"]):
        result["activity_preference"] = "art"
    elif any(kw in text for kw in ["户外", "公园", "散步", "走走", "逛逛"]):
        result["activity_preference"] = "outdoor"
    elif any(kw in text for kw in ["玩", "娱乐", "游戏", "乐"]):
        result["activity_preference"] = "entertainment"
    elif any(kw in text for kw in ["休闲", "放松", "休息", "轻松"]):
        result["activity_preference"] = "relax"
    elif any(kw in text for kw in ["吃", "美食", "餐厅", "好吃"]):
        result["activity_preference"] = "food"

    # ===== 解析餐饮偏好 =====
    if any(kw in text for kw in ["轻食", "健康餐", "减脂", "减肥", "控糖", "低卡", "低碳"]):
        result["food_preference"] = "healthy"
        result["diet_goal"] = "health_diet"
    elif any(kw in text for kw in ["辣", "火锅", "烧烤", "重口"]):
        result["food_preference"] = "spicy"
    elif any(kw in text for kw in ["西餐", "牛排", "汉堡"]):
        result["food_preference"] = "western"
    else:
        result["food_preference"] = "chinese"

    # ===== 应用默认值补全缺失信息 =====
    if result["start_time"] is None:
        result["start_time"] = default_when_missing.get("exact_start_time", "14:00")
        result["missing_slots"].append("start_time")

    if result["duration_hours"] is None:
        result["duration_hours"] = default_when_missing.get("duration_hours", defaults.get("duration_hours", 4))
        result["missing_slots"].append("duration_hours")

    if result["budget_level"] is None:
        result["budget_level"] = default_when_missing.get("budget_level", "medium")
        result["missing_slots"].append("budget_level")

    if result["people_count"] is None:
        result["missing_slots"].append("people_count")

    if result["companions"] is None:
        default_companions = default_when_missing.get("companions", defaults.get("companions"))
        if default_companions and default_companions != "unknown":
            result["companions"] = default_companions
        result["missing_slots"].append("companions")

    if result["location"] is None:
        result["location"] = defaults.get("default_location", "mock_home_location")
        result["missing_slots"].append("location")

    # 根据产品规则，某些缺失信息不需要追问
    clarification_rules = rules.get("clarification_rules", {})
    do_not_ask = clarification_rules.get("do_not_ask_if_missing", [])

    # 过滤掉不需要追问的缺失槽位
    result["missing_slots"] = [
        slot for slot in result["missing_slots"]
        if slot not in do_not_ask
    ]

    scenario_result = detect_scenario_type(user_input, rules, transportation=result.get("transportation"))
    result.update(scenario_result)
    labels = scenario_result.get("scenario_labels", {})
    result.update({
        "companion_context": labels.get("companion_context", []),
        "relation_context": labels.get("relation_context", []),
        "primary_intent": labels.get("primary_intent"),
        "context_modifiers": labels.get("context_modifiers", []),
        "hard_constraints": labels.get("hard_constraints", []),
        "soft_preferences": labels.get("soft_preferences", []),
        "should_ask": labels.get("should_ask", []),
        "should_not_assume": labels.get("should_not_assume", []),
        "recommendation_style": labels.get("recommendation_style"),
    })
    return result


def get_scoring_explanation_prompt(plan_summary: str, scores: Dict[str, float]) -> str:
    """
    生成评分解释提示词

    Args:
        plan_summary: 方案摘要
        scores: 各项得分

    Returns:
        解释文本
    """
    explanations = []

    if scores.get("time_fit", 0) >= 18:
        explanations.append("时间安排合理，节奏舒适")
    elif scores.get("time_fit", 0) >= 12:
        explanations.append("时间安排尚可")
    else:
        explanations.append("时间略显紧张")

    if scores.get("distance_fit", 0) >= 18:
        explanations.append("距离很近，通勤方便")
    elif scores.get("distance_fit", 0) >= 12:
        explanations.append("距离适中")
    else:
        explanations.append("距离稍远")

    if "child_friendly" in scores and scores.get("child_friendly", 0) >= 18:
        explanations.append("非常适合儿童参与")
    elif "child_friendly" in scores and scores.get("child_friendly", 0) >= 12:
        explanations.append("儿童可以参与")

    if "diet_friendly" in scores and scores.get("diet_friendly", 0) >= 13:
        explanations.append("餐饮健康减脂友好")

    risk_score = scores.get("availability_risk", scores.get("booking_risk", 0))
    if risk_score >= 8:
        explanations.append("预约风险低")

    return "；".join(explanations) if explanations else "综合评分良好"


def get_recommendation_reason(plan: Dict[str, Any]) -> str:
    """
    生成推荐理由

    Args:
        plan: 方案信息

    Returns:
        推荐理由文本
    """
    reasons = []

    # 基于方案的推荐理由
    activities = plan.get("activities", [])
    restaurant = plan.get("restaurant", {})
    score = plan.get("score", 0)

    if score >= 85:
        reasons.append("综合评分优秀")
    elif score >= 70:
        reasons.append("综合评分良好")

    if activities:
        child_friendly_count = sum(1 for a in activities if a.get("child_friendly"))
        if child_friendly_count == len(activities):
            reasons.append("所有活动都适合儿童")

    if restaurant.get("diet_friendly"):
        reasons.append("餐厅兼顾减脂需求")

    if restaurant.get("child_friendly"):
        reasons.append("餐厅儿童友好")

    # 随机添加一些推荐理由
    extra_reasons = [
        "整体时间控制得当",
        "活动与餐饮搭配合理",
        "预约风险较低",
        "性价比高",
        "距离较近通勤便利",
        "体验丰富多样"
    ]

    # 随机选择1-2个额外理由
    selected_extras = random.sample(extra_reasons, min(2, len(extra_reasons)))
    reasons.extend(selected_extras)

    # 去重并组合
    unique_reasons = list(dict.fromkeys(reasons))
    return "。".join(unique_reasons[:4]) + "。"


def get_fallback_explanation(fallback_type: str, original_item: str, replacement: str) -> str:
    """
    生成异常处理的解释说明

    Args:
        fallback_type: 异常类型
        original_item: 原选项
        replacement: 替代选项

    Returns:
        解释文本
    """
    explanations = {
        "restaurant_unavailable": f"原餐厅 [{original_item}] 已满座，已为您切换至同商圈备选 [{replacement}]",
        "activity_unavailable": f"原活动 [{original_item}] 不可预约，已为您更换为无需预约的 [{replacement}]",
        "route_too_far": f"原方案路线过远，已重新组合更近的活动和餐厅",
        "not_child_friendly": f"原选项 [{original_item}] 不适合儿童，已剔除",
        "diet_unfriendly": f"[{original_item}] 饮食选择不够健康，已优先推荐更适合减脂的 [{replacement}]",
    }

    return explanations.get(fallback_type, f"[{original_item}] 不可行，已切换至 [{replacement}]")
