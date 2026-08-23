from __future__ import annotations

from dataclasses import replace
import re

from .model import ProofGoal, ProofSnapshot, ResidualClassification, normalize_goal_text


def _contains(text: str, *patterns: str) -> list[str]:
    return [pattern for pattern in patterns if pattern in text]


def classify_goal(goal: ProofGoal) -> ResidualClassification:
    text = normalize_goal_text(" ".join((*goal.hypotheses, goal.conclusion)))
    conclusion = normalize_goal_text(goal.conclusion)

    if goal.disposition == "shelved" and conclusion in {
        "expr",
        "cmd",
        "list String.string",
        "list string",
    }:
        return ResidualClassification(
            "internal_synthesis_witness",
            "high",
            ("bare shelved witness type",),
            actionable=False,
        )

    signals = _contains(conclusion, "DEXPR", "WeakestPrecondition.dexpr")
    if signals:
        return ResidualClassification("expression_compilation", "high", tuple(signals))

    control_signals = _contains(
        text,
        "ExitToken",
        "map.remove_many",
        "map.put",
        "map.remove",
    )
    map_operations = sum(
        text.count(item) for item in ("map.put", "map.remove", "map.remove_many")
    )
    if conclusion.startswith("map.remove_many ") or map_operations >= 2:
        return ResidualClassification(
            "control_flow_or_locals", "high", tuple(control_signals)
        )

    semantic_signals = _contains(
        conclusion,
        "ListArray.fold_left",
        "ranged_for",
        "ranged_for_u",
        "ranged_for_s",
    )
    if "_spec" in conclusion or semantic_signals:
        return ResidualClassification(
            "semantic_invariant",
            "high" if "_spec" in conclusion else "medium",
            tuple(
                (["independent specification"] if "_spec" in conclusion else [])
                + semantic_signals
            ),
        )

    bound_signals = _contains(
        conclusion,
        "byte.unsigned",
        "word.unsigned",
        "word.signed",
        "2 ^ width",
        "2 ^ (width - 1)",
    )
    if bound_signals and ("<" in conclusion or "<=" in conclusion):
        return ResidualClassification(
            "representation_or_bounds", "high", tuple(bound_signals)
        )

    if "ExitToken" in text:
        return ResidualClassification(
            "control_flow_or_locals",
            "medium",
            tuple(control_signals),
        )

    frame_signals = _contains(
        conclusion,
        "sep ",
        "sizedlistarray_value",
        "ListArray.put",
        "VectorArray.put",
    )
    if frame_signals:
        return ResidualClassification("mutation_or_frame", "medium", tuple(frame_signals))

    binding_signals = _contains(
        conclusion,
        "WP_nlet",
        "WP_nlet_eq",
        "WeakestPrecondition.cmd",
    )
    if binding_signals:
        return ResidualClassification("binding_compilation", "medium", tuple(binding_signals))

    cleanup_signals = [
        signal
        for signal, pattern in (
            ("map lookup", r"\bmap\.get\b"),
            ("convertible relation", r"\bConvertible_"),
            ("transparent binding", r"\bnlet\b"),
        )
        if re.search(pattern, conclusion)
    ]
    if cleanup_signals:
        return ResidualClassification("cleanup_or_integration", "low", tuple(cleanup_signals))

    return ResidualClassification("unknown", "low", ())


def classify_snapshot(snapshot: ProofSnapshot) -> ProofSnapshot:
    return ProofSnapshot(
        goals=tuple(
            replace(goal, classification=classify_goal(goal)) for goal in snapshot.goals
        )
    )
