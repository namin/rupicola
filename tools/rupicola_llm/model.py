from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
from typing import Any


_EVAR_RE = re.compile(r"\?(?:Goal|M|X|evar)[0-9_]+", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_goal_text(text: str) -> str:
    """Normalize presentation-only differences while preserving goal shape."""

    text = text.replace("\u00a0", " ")
    text = _EVAR_RE.sub("?evar", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class SourcePhrase:
    text: str
    start_offset: int
    end_offset: int
    start_line: int
    end_line: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReplayPlan:
    file: str
    theorem: str
    phrases: tuple[SourcePhrase, ...]
    declaration_index: int
    proof_index: int
    stop_index: int

    @property
    def stop_phrase(self) -> SourcePhrase:
        return self.phrases[self.stop_index]


@dataclass(frozen=True)
class ResidualClassification:
    category: str
    confidence: str
    signals: tuple[str, ...] = ()
    actionable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "confidence": self.confidence,
            "signals": list(self.signals),
            "actionable": self.actionable,
        }


@dataclass(frozen=True)
class Evidence:
    path: str
    line: int
    declaration: str
    kind: str
    score: int
    reasons: tuple[str, ...]
    snippet: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "line": self.line,
            "declaration": self.declaration,
            "kind": self.kind,
            "score": self.score,
            "reasons": list(self.reasons),
            "snippet": self.snippet,
        }


@dataclass(frozen=True)
class ProofGoal:
    goal_id: str
    hypotheses: tuple[str, ...]
    conclusion: str
    name: str | None
    disposition: str
    classification: ResidualClassification | None = None
    evidence: tuple[Evidence, ...] = ()

    @property
    def fingerprint(self) -> str:
        return sha256_json(
            {
                "hypotheses": [normalize_goal_text(h) for h in self.hypotheses],
                "conclusion": normalize_goal_text(self.conclusion),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.goal_id,
            "name": self.name,
            "disposition": self.disposition,
            "fingerprint": self.fingerprint,
            "hypotheses": list(self.hypotheses),
            "conclusion": self.conclusion,
        }
        if self.classification is not None:
            result["classification"] = self.classification.to_dict()
        result["evidence"] = [item.to_dict() for item in self.evidence]
        return result


@dataclass(frozen=True)
class ProofSnapshot:
    goals: tuple[ProofGoal, ...]

    @property
    def fingerprint(self) -> str:
        return sha256_json([goal.fingerprint for goal in self.goals])

    def to_dict(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        dispositions: dict[str, int] = {}
        actionable_count = 0
        for goal in self.goals:
            dispositions[goal.disposition] = dispositions.get(goal.disposition, 0) + 1
            if goal.classification is not None:
                category = goal.classification.category
                counts[category] = counts.get(category, 0) + 1
                if goal.classification.actionable:
                    actionable_count += 1
        return {
            "fingerprint": self.fingerprint,
            "goal_count": len(self.goals),
            "actionable_goal_count": actionable_count,
            "auxiliary_goal_count": len(self.goals) - actionable_count,
            "counts_by_disposition": dict(sorted(dispositions.items())),
            "counts_by_class": dict(sorted(counts.items())),
            "goals": [goal.to_dict() for goal in self.goals],
        }


@dataclass(frozen=True)
class Diagnostic:
    kind: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    suggestion: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "message": self.message,
            "details": self.details,
            "suggestion": self.suggestion,
        }
