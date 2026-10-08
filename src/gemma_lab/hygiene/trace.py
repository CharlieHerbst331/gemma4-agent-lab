"""Normalize trace JSON into tool events.

Recognized shapes are the synthetic `gemma-lab/trace/v1` event list, a small
ADK-like `function_call` / `function_response` shape, and ATIF steps. ATIF tool
output is read from `observation.results[]` and from `observation.content`
(a string or a list of parts). A later observation-only step can fill the
matching call. Anything else is `unknown`. Unknown traces are never treated
as a fallback diff.
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
        observation = step.get("observation")
        outputs = _atif_outputs(observation)
        content = _observation_text(observation)
        obs_tool = _observation_tool(observation)
        named = [
            call
            for call in calls
            if isinstance(call, dict) and str(call.get("function_name") or "")
        ]
        for call in named:
            name = str(call.get("function_name") or "")
            call_id = str(call.get("tool_call_id") or "")
            output = outputs.get(call_id, "")
            if not output and len(named) == 1:
                output = outputs.get("", "")
            if not output and content and (len(named) == 1 or name == obs_tool):
                output = content
            arguments = call.get("arguments")
            if arguments is None:
                arguments = {}
            events.append(ToolEvent(_call_author(call, step, root), name, arguments, output))
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
    observation = step.get("observation")
    content = _observation_text(observation)
    tool_name = _observation_tool(observation)
    if not content or not tool_name:
        return
    extra = observation.get("extra") if isinstance(observation, dict) else None
    author = ""
    if isinstance(extra, dict) and extra.get("author"):
        author = str(extra["author"])
    else:
        author = _step_author(step, root)
    for item in reversed(events):
        if item.tool == tool_name and item.agent == author and not item.output:
            item.output = content
            return


def _observation_tool(observation) -> str:
    if not isinstance(observation, dict):
        return ""
    extra = observation.get("extra")
    if isinstance(extra, dict) and extra.get("tool_name"):
        return str(extra["tool_name"])
    return ""


def _observation_text(observation) -> str:
    if not isinstance(observation, dict):
        return ""
    return _content_text(observation.get("content"))


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


def _atif_outputs(observation) -> dict[str, str]:
    found: dict[str, str] = {}
    if not isinstance(observation, dict):
        return found
    results = observation.get("results")
    if not isinstance(results, list):
        return found
    loose = []
    for result in results:
        if not isinstance(result, dict):
            continue
        content = _content_text(result.get("content"))
        source = result.get("source_call_id")
        if source:
            found[str(source)] = content
        elif content:
            loose.append(content)
    if loose:
        found[""] = "\n".join(loose)
    return found


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)
