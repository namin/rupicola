from __future__ import annotations

from collections import deque
import codecs
import copy
from dataclasses import dataclass
import os
from pathlib import Path
import selectors
import subprocess
import time
from typing import Any
import xml.etree.ElementTree as ET

from .model import ProofGoal, ProofSnapshot, SourcePhrase
from .project import Project


class RocqIdeError(RuntimeError):
    pass


class RocqProcessError(RocqIdeError):
    pass


@dataclass(frozen=True)
class RocqCommandError(RocqIdeError):
    message: str
    state_id: int | None = None
    location: dict[str, str] | None = None
    phrase: SourcePhrase | None = None

    def __str__(self) -> str:
        position = ""
        if self.phrase is not None:
            position = f" near line {self.phrase.start_line}"
        return f"{self.message}{position}"


class _XmlResponseStream:
    """Incrementally decode coqidetop's adjacent top-level XML values."""

    def __init__(self) -> None:
        self._parser = ET.XMLPullParser(events=("start", "end"))
        self._parser.feed('<!DOCTYPE stream [<!ENTITY nbsp "&#160;">]><stream>')
        self._decoder = codecs.getincrementaldecoder("utf-8")()
        self._depth = 0
        self.responses: deque[ET.Element] = deque()
        self.messages: deque[str] = deque(maxlen=100)
        self._drain_events()

    def feed(self, data: bytes) -> None:
        text = self._decoder.decode(data)
        if text:
            self._parser.feed(text)
            self._drain_events()

    def _drain_events(self) -> None:
        for event, element in self._parser.read_events():
            if event == "start":
                self._depth += 1
                continue
            if self._depth == 2:
                if element.tag == "value":
                    self.responses.append(copy.deepcopy(element))
                elif element.tag == "feedback":
                    message = element.find(".//message")
                    if message is not None:
                        rendered = render_pp(message)
                        if rendered:
                            self.messages.append(rendered)
                element.clear()
            self._depth -= 1


class CoqIdeDriver:
    def __init__(self, project: Project, timeout_seconds: float = 120.0) -> None:
        self.project = project
        self.timeout_seconds = timeout_seconds
        self._process: subprocess.Popen[bytes] | None = None
        self._selector: selectors.BaseSelector | None = None
        self._stream = _XmlResponseStream()
        self._stderr = bytearray()
        self._state_id: int | None = None
        self._edit_id = 0

    def __enter__(self) -> "CoqIdeDriver":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def start(self) -> None:
        if self._process is not None:
            raise RocqIdeError("coqidetop driver is already running")
        try:
            process = subprocess.Popen(
                self.project.coqidetop_args(),
                cwd=self.project.root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                start_new_session=True,
            )
        except OSError as error:
            raise RocqProcessError(f"could not start coqidetop: {error}") from error
        assert process.stdout is not None
        assert process.stderr is not None
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        self._process = process
        self._selector = selector

    def initialize(self, file: Path) -> int:
        option = ET.Element("option", {"val": "some"})
        _string(option, str(file.resolve()))
        response = self._call("Init", option)
        self._state_id = _required_state_id(response)
        return self._state_id

    def add(self, phrase: SourcePhrase) -> int:
        if self._state_id is None:
            raise RocqIdeError("coqidetop must be initialized before adding phrases")
        self._edit_id += 1
        outer = ET.Element("pair")
        left = ET.SubElement(outer, "pair")
        command_and_state = ET.SubElement(left, "pair")
        command = ET.SubElement(command_and_state, "pair")
        _string(command, phrase.text)
        _int(command, self._edit_id)
        state = ET.SubElement(command_and_state, "pair")
        ET.SubElement(state, "state_id", {"val": str(self._state_id)})
        ET.SubElement(state, "bool", {"val": "false"})
        _int(left, phrase.start_offset)
        location = ET.SubElement(outer, "pair")
        _int(location, phrase.start_line)
        _int(location, 0)

        try:
            response = self._call("Add", outer)
        except RocqCommandError as error:
            raise RocqCommandError(
                message=error.message,
                state_id=error.state_id,
                location=error.location,
                phrase=phrase,
            ) from error
        self._state_id = _required_state_id(response)
        return self._state_id

    def join(self) -> None:
        boolean = ET.Element("bool", {"val": "true"})
        self._call("Status", boolean)

    def goals(self) -> ProofSnapshot:
        response = self._call("Goal", ET.Element("unit"))
        option = _first_child(response)
        if option.tag != "option":
            raise RocqProcessError(f"unexpected Goal response: {ET.tostring(response)!r}")
        if option.attrib.get("val") == "none":
            return ProofSnapshot(())
        goals_element = option.find("goals")
        if goals_element is None:
            raise RocqProcessError("Goal response did not contain a goals element")
        lists = [child for child in goals_element if child.tag == "list"]
        if len(lists) != 4:
            raise RocqProcessError(
                f"Goal response contained {len(lists)} goal collections instead of four"
            )

        goals: list[ProofGoal] = []
        goals.extend(_parse_goal_list(lists[0], "focused"))
        for pair in lists[1]:
            if pair.tag != "pair":
                continue
            background_lists = [child for child in pair if child.tag == "list"]
            for background_list in background_lists:
                goals.extend(_parse_goal_list(background_list, "background"))
        goals.extend(_parse_goal_list(lists[2], "shelved"))
        goals.extend(_parse_goal_list(lists[3], "given_up"))
        return ProofSnapshot(tuple(goals))

    def replay(self, file: Path, phrases: tuple[SourcePhrase, ...]) -> ProofSnapshot:
        self.initialize(file)
        for phrase in phrases:
            self.add(phrase)
        self.join()
        return self.goals()

    def close(self) -> None:
        process = self._process
        selector = self._selector
        if process is None:
            return
        if process.poll() is None:
            try:
                self._call("Quit", ET.Element("unit"), timeout_seconds=2.0)
            except RocqIdeError:
                process.terminate()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2.0)
        if selector is not None:
            selector.close()
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        self._process = None
        self._selector = None

    def _call(
        self, name: str, payload: ET.Element, timeout_seconds: float | None = None
    ) -> ET.Element:
        process = self._process
        if process is None or process.stdin is None:
            raise RocqProcessError("coqidetop is not running")
        call = ET.Element("call", {"val": name})
        call.append(payload)
        encoded = ET.tostring(call, encoding="utf-8") + b"\n"
        try:
            process.stdin.write(encoded)
            process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise RocqProcessError(self._process_failure_message(error)) from error
        response = self._next_response(
            timeout_seconds if timeout_seconds is not None else self.timeout_seconds
        )
        if response.attrib.get("val") == "fail":
            raise _command_error(response)
        if response.attrib.get("val") != "good":
            raise RocqProcessError(
                f"coqidetop returned an unknown value status: {response.attrib!r}"
            )
        return response

    def _next_response(self, timeout_seconds: float) -> ET.Element:
        deadline = time.monotonic() + timeout_seconds
        while True:
            if self._stream.responses:
                return self._stream.responses.popleft()
            process = self._process
            selector = self._selector
            if process is None or selector is None:
                raise RocqProcessError("coqidetop is not running")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RocqProcessError(
                    f"timed out after {timeout_seconds:.1f}s waiting for coqidetop"
                )
            events = selector.select(remaining)
            if not events:
                continue
            for key, _ in events:
                try:
                    data = os.read(key.fileobj.fileno(), 65536)
                except OSError as error:
                    raise RocqProcessError(self._process_failure_message(error)) from error
                if not data:
                    try:
                        selector.unregister(key.fileobj)
                    except KeyError:
                        pass
                    continue
                if key.data == "stdout":
                    try:
                        self._stream.feed(data)
                    except ET.ParseError as error:
                        raise RocqProcessError(
                            f"invalid XML from coqidetop: {error}"
                        ) from error
                else:
                    self._stderr.extend(data)
                    if len(self._stderr) > 131072:
                        del self._stderr[:-131072]
            if process.poll() is not None and not self._stream.responses:
                raise RocqProcessError(self._process_failure_message())

    def _process_failure_message(self, error: BaseException | None = None) -> str:
        parts = ["coqidetop terminated before returning a response"]
        if error is not None:
            parts.append(str(error))
        stderr = self._stderr.decode("utf-8", errors="replace").strip()
        if stderr:
            parts.append(stderr)
        if self._stream.messages:
            parts.append(self._stream.messages[-1])
        return ": ".join(parts)


def _string(parent: ET.Element, value: str) -> ET.Element:
    element = ET.SubElement(parent, "string")
    element.text = value
    return element


def _int(parent: ET.Element, value: int) -> ET.Element:
    element = ET.SubElement(parent, "int")
    element.text = str(value)
    return element


def _first_child(element: ET.Element) -> ET.Element:
    try:
        return next(iter(element))
    except StopIteration as error:
        raise RocqProcessError(f"empty coqidetop response: {ET.tostring(element)!r}") from error


def _required_state_id(response: ET.Element) -> int:
    state = response.find(".//state_id")
    if state is None or "val" not in state.attrib:
        raise RocqProcessError(
            f"coqidetop response did not contain a state ID: {ET.tostring(response)!r}"
        )
    return int(state.attrib["val"])


def _command_error(response: ET.Element) -> RocqCommandError:
    state = response.find("state_id")
    location = response.find("./option/loc")
    pp_nodes = [child for child in response if child.tag in {"ppdoc", "richpp"}]
    message = render_pp(pp_nodes[-1]) if pp_nodes else render_pp(response)
    return RocqCommandError(
        message=message or "Rocq rejected a command",
        state_id=int(state.attrib["val"]) if state is not None else None,
        location=dict(location.attrib) if location is not None else None,
    )


def render_pp(element: ET.Element) -> str:
    def render(node: ET.Element) -> str:
        if node.tag == "string":
            return node.text or ""
        if node.tag == "ppdoc":
            variant = node.attrib.get("val")
            children = list(node)
            if variant == "string":
                return render(children[0]) if children else ""
            if variant == "glue":
                sequence = children[0] if children else None
                return "".join(render(child) for child in sequence) if sequence is not None else ""
            if variant in {"box", "tag"}:
                pair = children[0] if children else None
                pair_children = list(pair) if pair is not None else []
                return render(pair_children[-1]) if pair_children else ""
            if variant == "break":
                return " "
            if variant == "newline":
                return "\n"
            if variant == "empty":
                return ""
            if variant == "comment":
                sequence = children[0] if children else None
                return "".join(render(child) for child in sequence) if sequence is not None else ""
        pieces: list[str] = []
        if node.text and node.tag not in {"int", "bool", "state_id"}:
            pieces.append(node.text)
        pieces.extend(render(child) for child in node)
        return "".join(pieces)

    text = render(element).replace("\u00a0", " ")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _parse_goal_list(element: ET.Element, disposition: str) -> list[ProofGoal]:
    return [
        _parse_goal(child, disposition)
        for child in element
        if child.tag == "goal"
    ]


def _parse_goal(element: ET.Element, disposition: str) -> ProofGoal:
    children = list(element)
    if len(children) != 4:
        raise RocqProcessError(
            f"goal record has {len(children)} fields instead of four: {ET.tostring(element)!r}"
        )
    goal_id = children[0].text or ""
    hypotheses = tuple(render_pp(hypothesis) for hypothesis in children[1])
    conclusion = render_pp(children[2])
    name_option = children[3]
    name_element = name_option.find("string")
    name = name_element.text if name_element is not None else None
    return ProofGoal(
        goal_id=goal_id,
        hypotheses=hypotheses,
        conclusion=conclusion,
        name=name,
        disposition=disposition,
    )
