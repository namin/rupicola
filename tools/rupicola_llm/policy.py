from __future__ import annotations

from collections import Counter
from pathlib import Path, PurePosixPath
import re

from .patches import ParsedPatch
from .source import SourcePlanError, split_phrases


EXTENSION_ROOT = PurePosixPath("src/Rupicola/Generated")


_UNSAFE_SOURCE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Admitted command", re.compile(r"\bAdmitted\b")),
    ("admit tactic", re.compile(r"\badmit\b")),
    ("axiom declaration", re.compile(r"\b(?:Axiom|Axioms|Conjecture)\b")),
    ("parameter declaration", re.compile(r"\b(?:Parameter|Parameters)\b")),
    ("aborted proof", re.compile(r"\bAbort\b")),
    (
        "unchecked cast",
        re.compile(r"\b(?:exact_no_check|vm_cast_no_check|native_cast_no_check)\b"),
    ),
    ("disabled guard checking", re.compile(r"\bUnset\s+Guard\s+Checking\b")),
    ("type-in-type", re.compile(r"\bSet\s+Type\s+In\s+Type\b")),
    (
        "plugin, source, or filesystem command",
        re.compile(
            r"(?m)^\s*(?:Declare\s+ML\s+Module|Add(?:\s+Rec)?\s+LoadPath|"
            r"Remove\s+LoadPath|Load\s+|Redirect\s+|Cd\s+|"
            r"(?:Separate\s+|Recursive\s+)?Extraction\b)"
        ),
    ),
)


def scope_violations(
    patch: ParsedPatch,
    target: str,
    scope: str,
    *,
    extension_root: PurePosixPath = EXTENSION_ROOT,
) -> list[str]:
    target_path = PurePosixPath(target)
    violations: list[str] = []
    for value in patch.paths:
        path = PurePosixPath(value)
        if ".git" in path.parts or ".rupicola" in path.parts:
            violations.append(f"protected path is not writable: {value}")
            continue
        if path == target_path:
            continue
        if scope == "project" and path.suffix == ".v" and _is_below(path, extension_root):
            continue
        if scope == "local":
            violations.append(f"local scope permits only the target proof: {value}")
        else:
            violations.append(
                f"project scope permits only the target and {extension_root.as_posix()}: {value}"
            )
    return violations


def source_policy_violations(
    original_root: Path,
    candidate_root: Path,
    paths: tuple[str, ...],
    scope: str,
    *,
    extension_root: PurePosixPath = EXTENSION_ROOT,
) -> list[str]:
    violations: list[str] = []
    for value in paths:
        relative = PurePosixPath(value)
        if relative.suffix != ".v":
            continue
        original_path = original_root.joinpath(*relative.parts)
        candidate_path = candidate_root.joinpath(*relative.parts)
        original = original_path.read_text(encoding="utf-8") if original_path.is_file() else ""
        candidate = candidate_path.read_text(encoding="utf-8")
        original_code = _code_only(original)
        candidate_code = _code_only(candidate)
        for label, pattern in _UNSAFE_SOURCE_PATTERNS:
            original_fragments = Counter(_matching_phrases(original_code, pattern))
            candidate_fragments = Counter(_matching_phrases(candidate_code, pattern))
            for fragment in candidate_fragments - original_fragments:
                violations.append(
                    f"{value} introduces an unsafe {label}: {fragment[:160]}"
                )

        if scope == "project" and _is_below(relative, extension_root):
            original_broad = Counter(_broad_exported_hints(original))
            candidate_broad = Counter(_broad_exported_hints(candidate))
            for phrase, count in (candidate_broad - original_broad).items():
                violations.append(
                    f"{value} introduces a broad or unnamed exported Hint Extern: {phrase}"
                )
                if count > 1:
                    violations.append(f"{value} repeats that unsafe hint {count} times")
    return violations


def _is_below(path: PurePosixPath, root: PurePosixPath) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _broad_exported_hints(source: str) -> list[str]:
    try:
        phrases = split_phrases(source)
    except SourcePlanError:
        return ["malformed Rocq source prevents exported-hint linting"]
    result: list[str] = []
    for phrase in phrases:
        code = _code_only(phrase.text)
        if re.search(r"#\[\s*export\s*\]\s*Hint\s+Extern\b", code) is None:
            continue
        match = re.search(
            r"Hint\s+Extern\s+\d+\s+(?P<pattern>[\s\S]*?)=>[\s\S]*"
            r":\s*(?P<database>[A-Za-z_][A-Za-z0-9_']*)\s*\.",
            code,
        )
        if match is None or not match.group("pattern").strip():
            result.append(" ".join(code.split())[:240])
    return result


def _matching_phrases(source: str, pattern: re.Pattern[str]) -> list[str]:
    try:
        phrases = [phrase.text for phrase in split_phrases(source)]
    except SourcePlanError:
        phrases = [source]
    return [" ".join(phrase.split()) for phrase in phrases if pattern.search(phrase)]


def _code_only(source: str) -> str:
    result: list[str] = []
    index = 0
    comment_depth = 0
    in_string = False
    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if comment_depth:
            if char == "(" and following == "*":
                comment_depth += 1
                result.extend("  ")
                index += 2
                continue
            if char == "*" and following == ")":
                comment_depth -= 1
                result.extend("  ")
                index += 2
                continue
            result.append("\n" if char == "\n" else " ")
            index += 1
            continue
        if in_string:
            if char == '"' and following == '"':
                result.extend("  ")
                index += 2
                continue
            if char == '"':
                in_string = False
            result.append("\n" if char == "\n" else " ")
            index += 1
            continue
        if char == "(" and following == "*":
            comment_depth = 1
            result.extend("  ")
            index += 2
            continue
        if char == '"':
            in_string = True
            result.append(" ")
            index += 1
            continue
        result.append(char)
        index += 1
    return "".join(result)
