#!/usr/bin/env python3
"""
Evaluate the weekend activity agent multi-label scenario classifier.

The script uses tests/scenario_eval_cases.yaml as a lightweight regression set.
It intentionally calls the local mock parser instead of any remote model.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prompts import parse_request_mock  # noqa: E402


DIMENSION_POINTS = {
    "companion_context": 15,
    "primary_intent": 15,
    "context_modifiers": 15,
    "hard_constraints": 20,
    "should_ask": 15,
    "no_over_assumption": 10,
    "recommendation_style": 10,
}


def as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def subset_score(expected: List[str], predicted: List[str], points: int, penalize_extra: bool = False) -> Tuple[float, bool]:
    expected_set = set(expected)
    predicted_set = set(predicted)
    if not expected_set:
        if not penalize_extra:
            return float(points), True
        return (float(points), True) if not predicted_set else (round(points * 0.5, 2), False)

    hit_ratio = len(expected_set & predicted_set) / len(expected_set)
    score = points * hit_ratio
    ok = expected_set.issubset(predicted_set)
    if penalize_extra:
        extra = predicted_set - expected_set
        if extra:
            score *= max(0.0, 1 - 0.2 * len(extra))
            ok = False
    return round(score, 2), ok


def over_assumption_violations(case: Dict[str, Any], predicted: Dict[str, Any]) -> List[str]:
    forbidden = set(as_list(case.get("expected_should_not_assume")))
    companion_context = set(as_list(predicted.get("companion_context")))
    relation_context = set(as_list(predicted.get("relation_context")))
    hard_constraints = set(as_list(predicted.get("hard_constraints")))

    violations = []
    if "children" in forbidden and (
        "family_with_children" in companion_context or "child_safety" in hard_constraints
    ):
        violations.append("children")
    if "spouse" in forbidden and ("spouse" in relation_context or "couple" in companion_context):
        violations.append("spouse")
    if "pet" in forbidden and ("pet" in companion_context or "pet_allowed" in hard_constraints):
        violations.append("pet")
    if "elderly" in forbidden and (
        "family_with_elderly" in companion_context or "elder_mobility" in hard_constraints
    ):
        violations.append("elderly")
    if "diet_goal" in forbidden and (
        predicted.get("diet_goal") not in (None, "none") or predicted.get("scenario_type") == "health_diet"
    ):
        violations.append("diet_goal")
    if "accessibility_need" in forbidden and "accessibility" in hard_constraints:
        violations.append("accessibility_need")
    return violations


def style_score(predicted: Dict[str, Any], points: int) -> Tuple[float, bool]:
    style = predicted.get("recommendation_style") or ""
    local_life_terms = ["中国", "本地生活", "商圈", "POI", "预约", "排队", "交通"]
    ok = sum(1 for term in local_life_terms if term in style) >= 3
    return (float(points), True) if ok else (0.0, False)


def evaluate_case(case: Dict[str, Any]) -> Dict[str, Any]:
    predicted = parse_request_mock(case["input"])

    failed_dimensions: List[str] = []
    score = 0.0

    companion_score, ok = subset_score(
        as_list(case.get("expected_companion_context")),
        as_list(predicted.get("companion_context")),
        DIMENSION_POINTS["companion_context"],
    )
    score += companion_score
    if not ok:
        failed_dimensions.append("companion_context")

    primary_ok = predicted.get("primary_intent") == case.get("expected_primary_intent")
    if primary_ok:
        score += DIMENSION_POINTS["primary_intent"]
    else:
        failed_dimensions.append("primary_intent")

    modifier_score, ok = subset_score(
        as_list(case.get("expected_context_modifiers")),
        as_list(predicted.get("context_modifiers")),
        DIMENSION_POINTS["context_modifiers"],
    )
    score += modifier_score
    if not ok:
        failed_dimensions.append("context_modifiers")

    hard_score, ok = subset_score(
        as_list(case.get("expected_hard_constraints")),
        as_list(predicted.get("hard_constraints")),
        DIMENSION_POINTS["hard_constraints"],
        penalize_extra=True,
    )
    score += hard_score
    if not ok:
        failed_dimensions.append("hard_constraints")

    ask_score, ok = subset_score(
        as_list(case.get("expected_should_ask")),
        as_list(predicted.get("should_ask")),
        DIMENSION_POINTS["should_ask"],
    )
    score += ask_score
    if not ok:
        failed_dimensions.append("should_ask")

    assumption_violations = over_assumption_violations(case, predicted)
    if not assumption_violations:
        score += DIMENSION_POINTS["no_over_assumption"]
    else:
        failed_dimensions.append("no_over_assumption")

    local_style_score, ok = style_score(predicted, DIMENSION_POINTS["recommendation_style"])
    score += local_style_score
    if not ok:
        failed_dimensions.append("recommendation_style")

    expected_labels = {
        "companion_context": as_list(case.get("expected_companion_context")),
        "primary_intent": case.get("expected_primary_intent"),
        "context_modifiers": as_list(case.get("expected_context_modifiers")),
        "hard_constraints": as_list(case.get("expected_hard_constraints")),
        "should_ask": as_list(case.get("expected_should_ask")),
        "should_not_assume": as_list(case.get("expected_should_not_assume")),
    }
    predicted_labels = {
        "companion_context": as_list(predicted.get("companion_context")),
        "relation_context": as_list(predicted.get("relation_context")),
        "primary_intent": predicted.get("primary_intent"),
        "context_modifiers": as_list(predicted.get("context_modifiers")),
        "hard_constraints": as_list(predicted.get("hard_constraints")),
        "soft_preferences": as_list(predicted.get("soft_preferences")),
        "should_ask": as_list(predicted.get("should_ask")),
        "scenario_type": predicted.get("scenario_type"),
        "scoring_profile": predicted.get("scoring_profile"),
    }

    return {
        "case_id": case.get("case_id"),
        "input": case.get("input"),
        "predicted_labels": predicted_labels,
        "expected_labels": expected_labels,
        "score": round(score, 2),
        "failed_dimensions": failed_dimensions,
        "hard_constraint_violation": "hard_constraints" in failed_dimensions,
        "over_assumption_violation": bool(assumption_violations),
        "over_assumptions": assumption_violations,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        default=str(ROOT / "tests" / "scenario_eval_cases.yaml"),
        help="Path to scenario eval cases YAML.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    with open(args.cases, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    cases = data.get("cases", [])
    if not cases:
        raise SystemExit("No cases found.")

    results = [evaluate_case(case) for case in cases]
    total = len(results)
    average_score = round(sum(item["score"] for item in results) / total, 2)
    overall_accuracy = round(sum(1 for item in results if item["score"] >= 80) / total, 4)
    hard_constraint_violation_count = sum(1 for item in results if item["hard_constraint_violation"])
    over_assumption_count = sum(1 for item in results if item["over_assumption_violation"])

    output = {
        "results": results,
        "overall_accuracy": overall_accuracy,
        "average_score": average_score,
        "hard_constraint_violation_count": hard_constraint_violation_count,
        "over_assumption_count": over_assumption_count,
    }

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0

    for item in results:
        print(f"{item['case_id']}: {item['score']}/100")
        print(f"  input: {item['input']}")
        print(f"  predicted labels: {json.dumps(item['predicted_labels'], ensure_ascii=False)}")
        print(f"  expected labels: {json.dumps(item['expected_labels'], ensure_ascii=False)}")
        print(f"  failed_dimensions: {item['failed_dimensions']}")
    print(f"overall_accuracy: {overall_accuracy}")
    print(f"average_score: {average_score}")
    print(f"hard_constraint_violation_count: {hard_constraint_violation_count}")
    print(f"over_assumption_count: {over_assumption_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
