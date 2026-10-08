"""Normalize trace JSON into tool events.

Recognized shapes are the synthetic `gemma-lab/trace/v1` event list, a small
ADK-like `function_call` / `function_response` shape, and ATIF steps. ATIF tool
output is read from `observation.results[]` and from `observation.content`
(a string or a list of parts). Parallel calls match an observation by
`tool_call_id` and otherwise by order. A later observation-only step can fill
the still-empty call. Anything else is `unknown`. Unknown traces are never
treated as a fallback diff.
"""

from dataclasses import dataclass, field


@dataclass
class ToolEvent:
    agent: str
    tool: str
    args: object = field(default_factory=dict)
    output: str = ""
    call_id: str = ""


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
    version = payload.get("schema_version")
    if isinstance(version, str) and version.startswith("ATIF"):
        steps = payload.get("steps")
        if not isinstance(steps, list):
            return TraceView("unknown", [], error)
        return TraceView("atif", _atif_events(payload), error)
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


def _atif_events(payload: dict) -> list[ToolEvent]:
    agent = payload.get("agent")
    if isinstance(agent, dict):
        root = str(agent.get("name") or "")
    elif isinstance(agent, str):
        root = agent
    else:
        root = ""
    events: list[ToolEvent] = []
    for step in payload.get("steps") or []:
        if not isinstance(step, dict):
            continue
        calls = step.get("tool_calls")
        if not isinstance(calls, list) or not calls:
            _attach_observation(events, step, root)
            continue
        named = [
            call
            for call in calls
            if isinstance(call, dict) and str(call.get("function_name") or "")
        ]
        created: list[ToolEvent] = []
        for call in named:
            name = str(call.get("function_name") or "")
            arguments = call.get("arguments")
            if arguments is None:
                arguments = {}
            created.append(
                ToolEvent(
                    _call_author(call, step, root),
                    name,
                    arguments,
                    "",
                    str(call.get("tool_call_id") or ""),
                )
            )
        events.extend(created)
        # Bind this step's observations to its own calls. One content blob must
        # not be copied onto every parallel call of the same tool.
        _apply_observations(created, _observations_from(step.get("observation")))
    return events


def _call_author(call: dict, step: dict, root: str) -> str:
    extra = call.get("extra")
    if isinstance(extra, dict) and extra.get("author"):
        return str(extra["author"])
    return _step_author(step, root)


def _step_author(step: dict, root: str) -> str:
    extra = step.get("extra")
    if isinstance(extra, dict):
        for key in ("author", "agent", "agent_name", "name"):
            if extra.get(key):
                return str(extra[key])
    for key in ("author", "agent_name"):
        if step.get(key):
            return str(step[key])
    return root


def _attach_observation(events: list[ToolEvent], step: dict, root: str) -> None:
    """Attach a later observation-only step to the matching call.

    Official ATIF can deliver one result of a parallel batch on a following
    source:system step that has observation.content and no tool_calls.
    """
    observations = _observations_from(step.get("observation"))
    if not observations:
        return
    author = _step_author(step, root)
    for item in observations:
        if not item["author"]:
            item["author"] = author
    _apply_observations(events, observations)


def _apply_observations(events: list[ToolEvent], observations: list[dict]) -> None:
    """Match by tool_call_id, then by order among calls that still have no output."""
    pending = []
    for item in observations:
        content = item.get("content") or ""
        if not content:
            continue
        call_id = item.get("call_id") or ""
        if call_id and _fill_call_id(events, call_id, content):
            continue
        pending.append(item)
    for item in pending:
        _fill_in_order(events, item)


def _fill_call_id(events: list[ToolEvent], call_id: str, content: str) -> bool:
    for event in events:
        if event.call_id == call_id and not event.output:
            event.output = content
            return True
    return any(event.call_id == call_id for event in events)


def _fill_in_order(events: list[ToolEvent], item: dict) -> None:
    tool = item.get("tool") or ""
    author = item.get("author") or ""
    for event in events:
        if event.output:
            continue
        if tool and event.tool != tool:
            continue
        if author and event.agent != author:
            continue
        event.output = item["content"]
        return


def _observations_from(observation) -> list[dict]:
    if observation is None:
        return []
    if isinstance(observation, list):
        found = []
        for item in observation:
            found.extend(_observations_from(item))
        return found
    if not isinstance(observation, dict):
        return []
    extra = observation.get("extra") if isinstance(observation.get("extra"), dict) else {}
    results = observation.get("results")
    if isinstance(results, list) and results:
        found = []
        for result in results:
            if isinstance(result, str):
                found.append(_observation_record("", extra, result))
                continue
            if not isinstance(result, dict):
                continue
            result_extra = result.get("extra") if isinstance(result.get("extra"), dict) else {}
            merged = {**extra, **result_extra}
            call_id = str(
                result.get("source_call_id")
                or result.get("tool_call_id")
                or merged.get("tool_call_id")
                or merged.get("source_call_id")
                or ""
            )
            found.append(_observation_record(call_id, merged, result.get("content")))
        return [item for item in found if item["content"]]
    return _content_observations(observation.get("content"), extra)


def _observation_record(call_id: str, extra: dict, content) -> dict:
    return {
        "call_id": call_id,
        "tool": str(extra.get("tool_name") or ""),
        "author": str(extra.get("author") or ""),
        "content": _content_text(content),
    }


def _content_observations(content, extra: dict) -> list[dict]:
    """One record per part when several calls share a step. Do not join them."""
    call_id = str(extra.get("tool_call_id") or extra.get("source_call_id") or "")
    if isinstance(content, list) and not call_id:
        parts = []
        for part in content:
            part_extra = extra
            part_id = ""
            body = part
            if isinstance(part, dict):
                nested = part.get("extra") if isinstance(part.get("extra"), dict) else {}
                part_extra = {**extra, **nested}
                part_id = str(
                    part.get("tool_call_id")
                    or part.get("source_call_id")
                    or part_extra.get("tool_call_id")
                    or ""
                )
                if "text" in part or "content" in part or "raw" in part:
                    body = part.get("text", part.get("content", part.get("raw")))
            record = _observation_record(part_id, part_extra, body)
            if record["content"]:
                parts.append(record)
        return parts
    record = _observation_record(call_id, extra, content)
    return [record] if record["content"] else []


def _content_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [_content_text(item) for item in value]
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        for key in ("text", "content", "raw"):
            if value.get(key) is not None:
                return _content_text(value[key])
        return ""
    return _text(value)


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)
