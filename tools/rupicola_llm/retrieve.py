from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import re

from .model import Evidence, ProofGoal, ProofSnapshot, normalize_goal_text
from .project import Project


_DECLARATION_RE = re.compile(
    r"(?m)^\s*(?:(?:Local|Global)\s+)?"
    r"(?P<kind>Definition|Fixpoint|Lemma|Theorem|Fact|Remark|Corollary|"
    r"Proposition|Instance|Ltac2?)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_']*)"
)
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_']*(?:\.[A-Za-z_][A-Za-z0-9_']*)*")

_CATEGORY_ANCHORS: dict[str, tuple[str, ...]] = {
    "expression_compilation": ("expr_compile", "expr_compiler", "DEXPR"),
    "binding_compilation": ("compile_", "WP_nlet", "compiler"),
    "semantic_invariant": ("fold_left", "ranged_for", "_spec", "invariant"),
    "representation_or_bounds": ("unsigned_range", "width_cases", "bounds", "range"),
    "control_flow_or_locals": (
        "ExitToken",
        "map.remove_many",
        "compile_break",
        "locals",
    ),
    "mutation_or_frame": ("sep", "ListArray.put", "frame", "array_value"),
    "cleanup_or_integration": ("compiler_cleanup", "Hint Rewrite", "Hint Unfold"),
}

_IGNORED_IDENTIFIERS = {
    "Prop",
    "Type",
    "Z",
    "nat",
    "bool",
    "byte",
    "word",
    "DEXPR",
    "map.of_list",
    "word_of_byte",
    "word.of_Z",
    "String.string",
    "Semantics.ExtSpec",
    "Bitwidth",
    "width",
    "mem",
    "locals",
    "fun",
    "let",
    "in",
    "if",
    "then",
    "else",
    "true",
    "false",
}


@dataclass(frozen=True)
class _Declaration:
    path: Path
    line: int
    kind: str
    name: str
    text: str


def retrieve_snapshot(
    project: Project,
    target: Path,
    snapshot: ProofSnapshot,
    *,
    limit_per_goal: int = 3,
) -> ProofSnapshot:
    declarations = _index_project(project, target)
    case_key = _case_key(target)
    goals = tuple(
        replace(
            goal,
            evidence=tuple(
                _rank(goal, declarations, project.root, case_key, limit_per_goal)
            ),
        )
        for goal in snapshot.goals
    )
    return ProofSnapshot(goals)


def _index_project(project: Project, target: Path) -> tuple[_Declaration, ...]:
    roots: list[Path] = []
    for load_path in project.load_paths:
        try:
            load_path.physical.relative_to(project.root)
        except ValueError:
            continue
        if load_path.logical == "Rupicola":
            roots.append(load_path.physical)
    if not roots:
        fallback = project.root / "src" / "Rupicola"
        if fallback.is_dir():
            roots.append(fallback)

    declarations: list[_Declaration] = []
    for root in roots:
        for path in sorted(root.rglob("*.v")):
            if path.resolve() == target.resolve():
                continue
            source = path.read_text(encoding="utf-8", errors="replace")
            matches = list(_DECLARATION_RE.finditer(source))
            for index, match in enumerate(matches):
                end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
                block = source[match.start() : end]
                declarations.append(
                    _Declaration(
                        path=path,
                        line=source.count("\n", 0, match.start()) + 1,
                        kind=match.group("kind"),
                        name=match.group("name"),
                        text=block,
                    )
                )
    return tuple(declarations)


def _rank(
    goal: ProofGoal,
    declarations: tuple[_Declaration, ...],
    root: Path,
    case_key: str,
    limit: int,
) -> list[Evidence]:
    category = goal.classification.category if goal.classification else "unknown"
    if category == "internal_synthesis_witness":
        return []
    terms = _distinct_terms(goal)
    specification_terms = tuple(
        term.rsplit(".", 1)[-1]
        for term in terms
        if term.rsplit(".", 1)[-1].lower().endswith("_spec")
    )
    anchors = _CATEGORY_ANCHORS.get(category, ())
    ranked: list[tuple[int, str, _Declaration, tuple[str, ...]]] = []

    for declaration in declarations:
        name_lower = declaration.name.lower()
        text_lower = declaration.text.lower()
        score = 0
        reasons: list[str] = []
        body_term_reasons: list[str] = []
        best_name_match: tuple[int, str] | None = None
        for term in terms:
            lower = term.lower()
            short = lower.rsplit(".", 1)[-1]
            if short == name_lower:
                candidate = (12, f"declaration matches {term}")
                if best_name_match is None or candidate[0] > best_name_match[0]:
                    best_name_match = candidate
            elif len(short) >= 4 and short in name_lower:
                candidate = (7, f"name contains {short}")
                if best_name_match is None or candidate[0] > best_name_match[0]:
                    best_name_match = candidate
            elif len(lower) >= 5 and lower in text_lower:
                body_term_reasons.append(f"body mentions {term}")
        if best_name_match is not None:
            score += best_name_match[0]
            reasons.append(best_name_match[1])

        normalized_name = _compact(declaration.name)
        if case_key and case_key in normalized_name:
            score += 15
            reasons.append(f"declaration belongs to target case {case_key}")
        elif case_key and case_key in _compact(declaration.path.stem):
            score += 8
            reasons.append(f"source belongs to target case {case_key}")

        if declaration.kind in {
            "Lemma",
            "Theorem",
            "Fact",
            "Remark",
            "Corollary",
            "Proposition",
        }:
            for specification in specification_terms:
                specification_lower = specification.lower()
                semantic_stem = _compact(specification[: -len("_spec")])
                if (
                    specification_lower in text_lower
                    and semantic_stem
                    and semantic_stem in normalized_name
                ):
                    score += 12
                    reasons.append(f"bridges goal to {specification}")
                    break
        score += min(6, 2 * len(body_term_reasons))
        reasons.extend(body_term_reasons[:3])
        for anchor in anchors:
            lower = anchor.lower()
            if lower in name_lower:
                score += 5
                reasons.append(f"name matches {anchor}")
            elif lower in text_lower:
                score += 1
                reasons.append(f"body matches {anchor}")
        if category != "expression_compilation" and declaration.kind in {
            "Lemma",
            "Theorem",
            "Fact",
            "Remark",
            "Corollary",
            "Proposition",
        }:
            score += 2
        if "/Lib/" in declaration.path.as_posix():
            score += 1
        if declaration.path.name.endswith("Spec.v"):
            score -= 5
        if "Baseline" in declaration.path.name:
            score -= 4
        if score > 0:
            ranked.append((score, declaration.name, declaration, tuple(dict.fromkeys(reasons))))

    ranked.sort(key=lambda item: (-item[0], item[1], str(item[2].path)))
    evidence: list[Evidence] = []
    seen: set[tuple[Path, str]] = set()
    for score, _, declaration, reasons in ranked:
        key = (declaration.path, declaration.name)
        if key in seen:
            continue
        seen.add(key)
        evidence.append(
            Evidence(
                path=str(declaration.path.relative_to(root)),
                line=declaration.line,
                declaration=declaration.name,
                kind=declaration.kind,
                score=score,
                reasons=reasons[:4],
                snippet=_snippet(declaration.text),
            )
        )
        if len(evidence) == limit:
            break
    return evidence


def _distinct_terms(goal: ProofGoal) -> tuple[str, ...]:
    text = normalize_goal_text(goal.conclusion)
    result: list[str] = []
    for identifier in _IDENTIFIER_RE.findall(text):
        short = identifier.rsplit(".", 1)[-1]
        if identifier in _IGNORED_IDENTIFIERS or short in _IGNORED_IDENTIFIERS:
            continue
        if len(short) < 4 and "_" not in short:
            continue
        if identifier not in result:
            result.append(identifier)
        if short.endswith("_spec"):
            stem = short[: -len("_spec")]
            if stem and stem not in result:
                result.append(stem)
    return tuple(result[:24])


def _snippet(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    snippet = "\n".join(lines[:8])
    if len(snippet) > 800:
        snippet = snippet[:797] + "..."
    return snippet


def _case_key(path: Path) -> str:
    stem = path.stem
    if stem.lower().startswith("llm"):
        stem = stem[3:]
    suffixes = ("baseline", "benchmark", "compiler", "generated", "proof", "spec", "support")
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if stem.lower().endswith(suffix):
                stem = stem[: -len(suffix)]
                changed = True
                break
    key = _compact(stem)
    return key if len(key) >= 5 else ""


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())
