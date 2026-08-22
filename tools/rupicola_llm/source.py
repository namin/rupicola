from __future__ import annotations

import re

from .model import ReplayPlan, SourcePhrase


class SourcePlanError(ValueError):
    pass


def _is_sentence_dot(source: str, index: int) -> bool:
    previous = source[index - 1] if index else ""
    following = source[index + 1] if index + 1 < len(source) else ""
    if previous == "." or following == ".":
        return False
    if not following or following.isspace():
        return True
    return following == "(" and index + 2 < len(source) and source[index + 2] == "*"


def split_phrases(source: str) -> tuple[SourcePhrase, ...]:
    """Split the command subset needed by the diagnostic proof replayer.

    Rocq itself remains the parser of record.  This scanner only finds likely
    command boundaries to feed to the interactive protocol.  It understands
    nested comments, quoted strings, qualified names, and Ltac's ``..`` token.
    A protocol parse error is reported with this scanner's source span.
    """

    phrases: list[SourcePhrase] = []
    start = 0
    index = 0
    line = 1
    start_line = 1
    comment_depth = 0
    in_string = False

    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""

        if comment_depth:
            if char == "(" and following == "*":
                comment_depth += 1
                index += 2
                continue
            if char == "*" and following == ")":
                comment_depth -= 1
                index += 2
                continue
            if char == "\n":
                line += 1
            index += 1
            continue

        if in_string:
            if char == '"':
                if following == '"':
                    index += 2
                    continue
                in_string = False
            if char == "\n":
                line += 1
            index += 1
            continue

        if char == "(" and following == "*":
            comment_depth = 1
            index += 2
            continue
        if char == '"':
            in_string = True
            index += 1
            continue
        if char == "\n":
            line += 1
            index += 1
            continue
        if char == "." and _is_sentence_dot(source, index):
            end = index + 1
            text = source[start:end]
            if text.strip():
                phrases.append(
                    SourcePhrase(
                        text=text,
                        start_offset=start,
                        end_offset=end,
                        start_line=start_line,
                        end_line=line,
                    )
                )
            start = end
            start_line = line
        index += 1

    if comment_depth:
        raise SourcePlanError("unterminated Rocq comment")
    if in_string:
        raise SourcePlanError("unterminated Rocq string")
    if source[start:].strip():
        raise SourcePlanError(
            f"unterminated Rocq phrase beginning near line {start_line}"
        )
    return tuple(phrases)


def _without_comments(text: str) -> str:
    result: list[str] = []
    index = 0
    depth = 0
    in_string = False
    while index < len(text):
        char = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if depth:
            if char == "(" and following == "*":
                depth += 1
                index += 2
                continue
            if char == "*" and following == ")":
                depth -= 1
                index += 2
                continue
            if char == "\n":
                result.append("\n")
            index += 1
            continue
        if in_string:
            result.append(char)
            if char == '"':
                if following == '"':
                    result.append(following)
                    index += 2
                    continue
                in_string = False
            index += 1
            continue
        if char == "(" and following == "*":
            depth = 1
            index += 2
            continue
        result.append(char)
        if char == '"':
            in_string = True
        index += 1
    return "".join(result)


def _declares_theorem(text: str, theorem: str) -> bool:
    clean = _without_comments(text)
    escaped = re.escape(theorem)
    ordinary = re.search(
        rf"\b(?:Theorem|Lemma|Fact|Remark|Corollary|Proposition)\s+{escaped}\b",
        clean,
    )
    derived = re.search(rf"\bDerive\b[\s\S]*\bas\s+{escaped}\s*\.", clean)
    return ordinary is not None or derived is not None


def _is_proof_start(text: str) -> bool:
    return re.fullmatch(r"\s*Proof(?:\s+using\s+[^.]*)?\s*\.\s*", _without_comments(text)) is not None


def _is_compile_phrase(text: str) -> bool:
    clean = _without_comments(text)
    return re.search(r"\b(?:compile|compile_setup|compile_step)\b", clean) is not None


def build_replay_plan(
    file: str, source: str, theorem: str, through_line: int | None = None
) -> ReplayPlan:
    phrases = split_phrases(source)
    declaration_indexes = [
        index for index, phrase in enumerate(phrases) if _declares_theorem(phrase.text, theorem)
    ]
    if not declaration_indexes:
        raise SourcePlanError(f"theorem {theorem!r} was not found in {file}")
    if len(declaration_indexes) > 1:
        raise SourcePlanError(f"theorem {theorem!r} is declared more than once in {file}")
    declaration_index = declaration_indexes[0]

    try:
        proof_index = next(
            index
            for index in range(declaration_index + 1, len(phrases))
            if _is_proof_start(phrases[index].text)
        )
    except StopIteration as error:
        raise SourcePlanError(f"no Proof command follows theorem {theorem!r}") from error

    if through_line is not None:
        if through_line < phrases[proof_index].start_line:
            raise SourcePlanError(
                f"line {through_line} is before the proof of theorem {theorem!r}"
            )
        candidates = [
            index
            for index in range(proof_index, len(phrases))
            if phrases[index].end_line <= through_line
        ]
        if not candidates:
            raise SourcePlanError(f"line {through_line} does not end a complete Rocq phrase")
        stop_index = candidates[-1]
    else:
        try:
            stop_index = next(
                index
                for index in range(proof_index + 1, len(phrases))
                if _is_compile_phrase(phrases[index].text)
            )
        except StopIteration as error:
            raise SourcePlanError(
                f"no compile tactic was found in the proof of theorem {theorem!r}; "
                "select a proof cursor with --line"
            ) from error

    for index in range(proof_index + 1, stop_index + 1):
        clean = _without_comments(phrases[index].text)
        if re.search(r"\b(?:Qed|Defined|Admitted|Abort)\s*\.", clean):
            raise SourcePlanError(
                f"the proof of theorem {theorem!r} ends before the selected diagnostic point"
            )

    return ReplayPlan(
        file=file,
        theorem=theorem,
        phrases=phrases[: stop_index + 1],
        declaration_index=declaration_index,
        proof_index=proof_index,
        stop_index=stop_index,
    )
