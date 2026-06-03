"""
验证 Issue 3 修复：户外活动偏好输入 → 户外方案输出。
运行: python3 tests/test_outdoor_fix.py
"""

import sys
sys.path.insert(0, ".")

from agent_harness import WeekendActivityAgent, SCENARIO_PREFERENCES
from tools import search_activities
from schemas import UserRequest


# -----------------------------------------------------------------------
# Test 1: classify_scenario_labels 对户外输入输出 outdoor_walk
# -----------------------------------------------------------------------
def test_scenario_classifier_outdoor():
    from prompts import parse_request

    result = parse_request("想在上海找个公园散散步，户外活动一下")

    # LLM 路径返回顶层字段，mock 路径嵌套在 scenario_labels 下
    primary_intent = result.get("primary_intent") or \
                     (result.get("scenario_labels") or {}).get("primary_intent", "")
    assert primary_intent in ("outdoor_walk", "mixed_plan"), \
        f"Expected outdoor_walk or mixed_plan, got '{primary_intent}'"

    activity_pref = result.get("activity_preference", "")
    labels = result.get("scenario_labels") or {}
    context_mods = labels.get("context_modifiers", result.get("context_modifiers", []))
    print(f"  primary_intent={primary_intent}, activity_preference={activity_pref}, "
          f"context_modifiers={context_mods}")
    return True


# -----------------------------------------------------------------------
# Test 2: search_activities 在户外偏好时排除室内活动
# -----------------------------------------------------------------------
def test_search_activities_filters_indoor():
    activities = search_activities(
        location="shanghai",
        preferences={"activity_style": "outdoor"},
    )
    for a in activities:
        indoor_attr = getattr(a, "indoor_outdoor", "")
        assert indoor_attr != "indoor", \
            f"Indoor activity {a.name} found when outdoor preferred (indoor_outdoor={indoor_attr})"

    has_outdoor = any(getattr(a, "indoor_outdoor", "") == "outdoor" for a in activities)
    assert has_outdoor, "No outdoor activities found in results"

    print(f"  Found {len(activities)} activities, all non-indoor")
    return True


# -----------------------------------------------------------------------
# Test 3: _sort_supply_by_scenario 将户外排在室内之前（Round 1 自由文本路径）
# -----------------------------------------------------------------------
def test_sort_ranks_outdoor_higher_free_text():
    agent = WeekendActivityAgent()
    request = UserRequest(
        raw_text="户外活动",
        activity_preference="outdoor",
        primary_intent="outdoor_walk",
        scenario_type="active_outdoor",
    )
    agent.state.locked_constraints = {}

    activities = search_activities(
        location="shanghai",
        preferences={"activity_style": "outdoor"},
    )
    if len(activities) < 2:
        print("  SKIP: not enough activities to compare")
        return True

    sorted_activities = agent._sort_supply_by_scenario(activities, request)

    first_outdoor_idx = None
    last_indoor_idx = None
    for idx, a in enumerate(sorted_activities):
        i_o = getattr(a, "indoor_outdoor", "")
        if i_o == "outdoor" and first_outdoor_idx is None:
            first_outdoor_idx = idx
        if i_o == "indoor":
            last_indoor_idx = idx

    if first_outdoor_idx is not None and last_indoor_idx is not None:
        assert first_outdoor_idx < last_indoor_idx, \
            f"Indoor ranked before outdoor: outdoor at {first_outdoor_idx}, indoor at {last_indoor_idx}"

    print(f"  Sorted {len(sorted_activities)}: first outdoor at idx {first_outdoor_idx}, "
          f"last indoor at idx {last_indoor_idx}")
    return True


# -----------------------------------------------------------------------
# Test 4: SCENARIO_PREFERENCES 包含 active_outdoor 条目
# -----------------------------------------------------------------------
def test_scenario_preferences_has_active_outdoor():
    prefs = SCENARIO_PREFERENCES.get("active_outdoor")
    assert prefs is not None, "No active_outdoor entry in SCENARIO_PREFERENCES"
    assert "activities" in prefs, "active_outdoor missing 'activities' key"
    assert "restaurants" in prefs, "active_outdoor missing 'restaurants' key"
    assert "avoid" in prefs, "active_outdoor missing 'avoid' key"
    assert any(kw in prefs["avoid"] for kw in ["mall", "ktv", "cinema"]), \
        "active_outdoor avoid list doesn't include key indoor types"
    print(f"  active_outdoor: restaurants={prefs['restaurants'][:3]}..., "
          f"activities={prefs['activities'][:3]}..., avoid={prefs['avoid'][:3]}...")
    return True


# -----------------------------------------------------------------------
# Test 5: build_candidate_plans 生成的方案户外活动 ≥ 室内活动
# -----------------------------------------------------------------------
def test_build_outdoor_plans():
    agent = WeekendActivityAgent()
    request = UserRequest(
        raw_text="想户外活动",
        start_time="14:00",
        duration_hours=4,
        location="shanghai",
        activity_preference="outdoor",
        primary_intent="outdoor_walk",
        scenario_type="active_outdoor",
    )
    agent.state.user_request = request

    activities = search_activities(
        location="shanghai",
        preferences={"activity_style": "outdoor"},
    )
    agent.state.found_activities = activities
    restaurants = agent.search_restaurants(request)
    agent.state.found_restaurants = restaurants
    plans = agent.build_candidate_plans(request, activities, restaurants)

    assert len(plans) > 0, "No plans generated"

    for plan in plans:
        outdoor_count = sum(
            1 for a in plan.activities
            if getattr(a, "indoor_outdoor", "") == "outdoor"
        )
        indoor_count = sum(
            1 for a in plan.activities
            if getattr(a, "indoor_outdoor", "") == "indoor"
        )
        assert outdoor_count >= indoor_count, \
            f"Plan '{plan.title}' has more indoor ({indoor_count}) than outdoor ({outdoor_count})"

    print(f"  Generated {len(plans)} plans, all outdoor-dominant")
    return True


# -----------------------------------------------------------------------
if __name__ == "__main__":
    tests = [
        ("classify_scenario_labels includes outdoor_walk", test_scenario_classifier_outdoor),
        ("search_activities filters indoor when outdoor preferred", test_search_activities_filters_indoor),
        ("_sort_supply_by_scenario ranks outdoor higher (free-text)", test_sort_ranks_outdoor_higher_free_text),
        ("SCENARIO_PREFERENCES has active_outdoor", test_scenario_preferences_has_active_outdoor),
        ("build_candidate_plans outdoor-dominant", test_build_outdoor_plans),
    ]

    passed = 0
    failed = 0
    for name, test_fn in tests:
        print(f"\n--- Test: {name} ---")
        try:
            test_fn()
            print(f"  PASSED")
            passed += 1
        except Exception as e:
            print(f"  FAILED: {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed}/{len(tests)} passed, {failed}/{len(tests)} failed")
    sys.exit(0 if failed == 0 else 1)
