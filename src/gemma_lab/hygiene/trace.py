"""Normalize trace JSON into tool events.

Recognized shapes are the synthetic `gemma-lab/trace/v1` event list and a small
ADK-like `function_call` / `function_response` shape. Anything else is `unknown`.
Unknown traces are never treated as a fallback diff.
"""

from dataclasses import dataclass, field


@dataclass
class ToolEvent:
    agent: str
    tool: str
    args: object = field(default_factory=dict)
    output: str = ""


@dataclass
class TraceView:
    schema: str
    events: list[ToolEvent]
    error_message: str = ""

    @property
    def recognized(self) -> bool:
        return self.schema not in {"unknown", "absent"}


def parse_trace(payload) -> TraceView:
    if payload is None:
        return TraceView("absent", [])
    if not isinstance(payload, dict):
        return TraceView("unknown", [])
    error = str(payload.get("error_message") or "")
    declared = payload.get("schema") or payload.get("trace_schema")
    events = payload.get("events")
    if events is None and isinstance(payload.get("trace"), list):
        events = payload["trace"]
        declared = declared or "adk-like"
    if not isinstance(events, list):
        return TraceView("unknown", [], error)
    if declared == "gemma-lab/trace/v1" or _all_normalized(events):
        parsed = [_normalized(event) for event in events if isinstance(event, dict)]
        return TraceView("gemma-lab/trace/v1", parsed, error)
    if events and all(_looks_adk(event) for event in events if isinstance(event, dict)):
        return TraceView("adk-like", _adk_events(events), error)
    if not events and declared:
        return TraceView(str(declared), [], error)
    return TraceView("unknown", [], error)


def _all_normalized(events: list) -> bool:
    if not events:
        return False
    return all(isinstance(event, dict) and _looks_normalized(event) for event in events)


def _looks_normalized(event: dict) -> bool:
    return "tool" in event and ("agent" in event or "author" in event)


def _looks_adk(event) -> bool:
    if not isinstance(event, dict):
        return False
    content = event.get("content")
    return isinstance(content, dict) and isinstance(content.get("parts"), list)


def _normalized(event: dict) -> ToolEvent:
    return ToolEvent(
        agent=str(event.get("agent") or event.get("author") or ""),
        tool=str(event.get("tool") or ""),
        args=event.get("args") if event.get("args") is not None else {},
        output=_text(
            event.get("output") if event.get("output") is not None else event.get("response")
        ),
    )


def _adk_events(events: list) -> list[ToolEvent]:
    parsed: list[ToolEvent] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        author = str(event.get("author") or "")
        for part in (event.get("content") or {}).get("parts") or []:
            if not isinstance(part, dict):
                continue
            call = part.get("function_call") or part.get("functionCall")
            response = part.get("function_response") or part.get("functionResponse")
            if isinstance(call, dict) and call.get("name"):
                parsed.append(
                    ToolEvent(
                        author, str(call["name"]), call.get("args") or {}, _text(call.get("output"))
                    )
                )
            elif isinstance(response, dict):
                name = str(response.get("name") or "")
                output = _text(response.get("response") or response.get("output"))
                attached = False
                for item in reversed(parsed):
                    if item.tool == name and item.agent == author and not item.output:
                        item.output = output
                        attached = True
                        break
                if not attached:
                    parsed.append(ToolEvent(author, name, {}, output))
    return parsed


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)
