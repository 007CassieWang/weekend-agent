#!/usr/bin/env python3
"""
端到端回归评估：运行完整 agent pipeline 并验证输出质量。

用法:
  python3 scripts/evaluate_e2e.py                    # 运行所有用例
  python3 scripts/evaluate_e2e.py --case family_weekend_plan  # 运行单个用例
  python3 scripts/evaluate_e2e.py --json             # JSON 输出
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_harness import run_agent_plan_only  # noqa: E402


def check_condition(result: Dict[str, Any], key: str, expected: Any) -> tuple[bool, str]:
    """检查单个条件。返回 (passed, message)。"""
    plan = result.get("best_plan", {})
    request = result.get("request", {})

    if key == "success":
        actual = result.get("success", False)
        return actual == expected, f"success: {actual} (expected {expected})"

    if key == "plan_has_activity":
        activities = plan.get("activities", [])
        actual = len(activities) > 0
        return actual == expected, f"has_activity: {actual} (expected {expected})"

    if key == "plan_has_restaurant":
        actual = plan.get("restaurant") is not None
        return actual == expected, f"has_restaurant: {actual} (expected {expected})"

    if key == "activity_child_friendly":
        activities = plan.get("activities", [])
        actual = all(a.get("child_friendly", False) for a in activities)
        return actual == expected, f"all_child_friendly: {actual}"

    if key == "total_duration_between":
        lo, hi = expected
        actual = plan.get("total_duration_minutes", 0)
        ok = lo <= actual <= hi
        return ok, f"duration: {actual}min (expected [{lo}, {hi}])"

    if key == "total_duration_under":
        actual = plan.get("total_duration_minutes", 0)
        ok = actual <= expected
        return ok, f"duration: {actual}min (expected <= {expected})"

    if key == "score_above":
        actual = plan.get("score", 0)
        ok = actual >= expected
        return ok, f"score: {actual} (expected >= {expected})"

    if key == "scenario_type":
        actual = request.get("scenario_type", "")
        ok = actual == expected
        return ok, f"scenario_type: {actual} (expected {expected})"

    if key == "scenario_type_in":
        actual = request.get("scenario_type", "")
        ok = actual in expected
        return ok, f"scenario_type: {actual} (expected in {expected})"

    if key == "companion_context_contains":
        actual = set(request.get("companion_context", []))
        ok = all(item in actual for item in expected)
        return ok, f"companion_context: {actual} (expected contains {expected})"

    if key == "should_not_assume":
        companion_ctx = set(request.get("companion_context", []))
        hard_constraints = set(request.get("hard_constraints", []))
        violations = []
        if "children" in expected and (
            "family_with_children" in companion_ctx or "child_safety" in hard_constraints
        ):
            violations.append("children")
        if "spouse" in expected and "couple" in companion_ctx:
            violations.append("spouse")
        if "pet" in expected and (
            "pet" in companion_ctx or "pet_allowed" in hard_constraints
        ):
            violations.append("pet")
        if "diet_goal" in expected and request.get("scenario_type") == "health_diet":
            violations.append("diet_goal")
        ok = len(violations) == 0
        return ok, f"over_assumptions: {violations if violations else 'none'}"

    if key == "state_has_retries":
        retry_count = result.get("state", {}).get("retry_count", 0)
        ok = retry_count > 0
        return ok, f"retry_count: {retry_count} (expected > 0)"

    return True, f"{key}: unchecked"


def evaluate_case(case: Dict[str, Any]) -> Dict[str, Any]:
    """运行单个用例并检查所有期望条件。"""
    case_id = case["case_id"]
    user_input = case["input"]
    expected = case.get("expected", {})

    # 运行 pipeline（plan_only，不执行）
    try:
        result = run_agent_plan_only(user_input)
    except Exception as exc:
        return {
            "case_id": case_id,
            "input": user_input,
            "passed": False,
            "error": str(exc),
            "checks": [],
            "result_summary": {},
        }

    checks = []
    all_passed = True

    for key, value in expected.items():
        passed, message = check_condition(result, key, value)
        checks.append({"key": key, "passed": passed, "message": message})
        if not passed:
            all_passed = False

    return {
        "case_id": case_id,
        "input": user_input,
        "passed": all_passed,
        "checks": checks,
        "result_summary": {
            "success": result.get("success"),
            "plan_title": result.get("best_plan", {}).get("title", ""),
            "score": result.get("best_plan", {}).get("score", 0),
            "duration_minutes": result.get("best_plan", {}).get("total_duration_minutes", 0),
            "scenario_type": result.get("request", {}).get("scenario_type", ""),
            "retry_count": result.get("state", {}).get("retry_count", 0),
            "relaxed_constraints": result.get("state", {}).get("relaxed_constraints", []),
        },
        "error": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="端到端 Agent 回归评估")
    parser.add_argument(
        "--cases",
        default=str(ROOT / "tests" / "e2e_eval_cases.yaml"),
        help="E2E eval cases YAML 路径",
    )
    parser.add_argument("--case", help="只运行指定 case_id")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    with open(args.cases, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    cases = data.get("cases", [])
    if not cases:
        raise SystemExit("No e2e eval cases found.")

    if args.case:
        cases = [c for c in cases if c["case_id"] == args.case]
        if not cases:
            raise SystemExit(f"Case '{args.case}' not found.")

    results = [evaluate_case(case) for case in cases]

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed
    error_count = sum(1 for r in results if r["error"])

    output = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "errors": error_count,
        "pass_rate": round(passed / total, 4) if total > 0 else 0,
        "results": results,
    }

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0 if failed == 0 else 1

    # 人类可读输出
    for r in results:
        status = "✅" if r["passed"] else "❌"
        print(f"\n{status} {r['case_id']}")
        print(f"   input: {r['input']}")
        if r["error"]:
            print(f"   ERROR: {r['error']}")
            continue
        summary = r["result_summary"]
        print(f"   plan: {summary['plan_title']}")
        print(f"   score: {summary['score']}, duration: {summary['duration_minutes']}min")
        print(f"   scenario: {summary['scenario_type']}, retries: {summary['retry_count']}")
        if summary["relaxed_constraints"]:
            print(f"   relaxed: {summary['relaxed_constraints']}")
        for check in r["checks"]:
            c_status = "  ✓" if check["passed"] else "  ✗"
            print(f"  {c_status} {check['key']}: {check['message']}")

    print(f"\n{'='*50}")
    print(f"Total: {total}  Passed: {passed}  Failed: {failed}  Errors: {error_count}")
    print(f"Pass Rate: {output['pass_rate']:.1%}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
