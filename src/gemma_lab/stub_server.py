"""OpenAI-compatible stub model server and a synthetic mock repository.

Any candidate CPU smoke test can import this module. The paired notebook tests
use the same server. The official harness treats a task as synthetic when
``repo`` starts with ``test/mock_repo`` and ``base_commit`` is ``123456``.
"""

from __future__ import annotations

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MOCK_REPO = "test/mock_repo"
MOCK_BASE_COMMIT = "123456"
MOCK_GIT_NAME = "gemma-lab"
MOCK_GIT_EMAIL = "gemma-lab@example.com"
MOCK_SOURCE = "mockpkg/calc.py"
BUGGY_LINE = "return a - b"
FIXED_LINE = "return a + b"


def write_mock_repo(dest):
    """Write a flat package the synthetic mock task can edit. Never extracts a snapshot."""
    dest = Path(dest)
    if dest.exists():
        raise FileExistsError(dest)
    package = dest / "mockpkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "calc.py").write_text(f"def add(a, b):\n    {BUGGY_LINE}\n")
    tests = dest / "tests"
    tests.mkdir()
    (tests / "test_calc.py").write_text(
        "from mockpkg.calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    (dest / "README.md").write_text("Synthetic mock repo for CPU smoke tests.\n")
    _baseline_git_commit(dest)
    return dest


def _baseline_git_commit(dest):
    """git init plus one commit. swegemma does not init the snapshot itself."""
    git = [
        "git",
        "-c",
        f"user.name={MOCK_GIT_NAME}",
        "-c",
        f"user.email={MOCK_GIT_EMAIL}",
        "-c",
        "commit.gpgsign=false",
    ]
    subprocess.run([*git, "init", "-b", "main"], cwd=dest, check=True, capture_output=True)
    subprocess.run([*git, "add", "-A"], cwd=dest, check=True, capture_output=True)
    subprocess.run(
        [*git, "commit", "-m", "baseline"],
        cwd=dest,
        check=True,
        capture_output=True,
    )


def mock_task(instance_id="mock-calc-001"):
    return {
        "instance_id": instance_id,
        "repo": MOCK_REPO,
        "base_commit": MOCK_BASE_COMMIT,
        "problem_statement": "add(a, b) subtracts. It should add.",
        "fail_to_pass": ["tests/test_calc.py::test_add"],
        "pass_to_pass": [],
    }


def is_synthetic_mock(task):
    if isinstance(task, dict):
        repo, commit = task.get("repo"), task.get("base_commit")
    else:
        repo, commit = getattr(task, "repo", None), getattr(task, "base_commit", None)
    return str(repo).startswith("test/mock_repo") and commit == MOCK_BASE_COMMIT


def tool_call(name, arguments=None, call_id=None):
    payload = arguments if isinstance(arguments, str) else json.dumps(arguments or {})
    return {
        "id": call_id or f"call_{name}",
        "type": "function",
        "function": {"name": name, "arguments": payload},
    }


def repair_turns(filepath=MOCK_SOURCE):
    """edit_file the known bug, then submit_patch."""
    return [
        {
            "content": None,
            "tool_calls": [
                tool_call(
                    "edit_file",
                    {"filepath": filepath, "old_string": BUGGY_LINE, "new_string": FIXED_LINE},
                )
            ],
        },
        {"content": None, "tool_calls": [tool_call("submit_patch", {})]},
    ]


def empty_submit_turns():
    return [{"content": None, "tool_calls": [tool_call("submit_patch", {})]}]


def message_text(request):
    parts = []
    for message in request.get("messages") or []:
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or ""))
                else:
                    parts.append(str(item))
    return "\n".join(parts)


class ScriptedResponder:
    """Choose a turn script by the first marker found in the request text."""

    def __init__(self, routes, default=None):
        self.routes = dict(routes)
        self.default = empty_submit_turns() if default is None else default
        self.cursors = {}
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        text = message_text(request)
        key = next((marker for marker in self.routes if marker in text), "")
        script = self.routes.get(key, self.default)
        index = self.cursors.get(key, 0)
        self.cursors[key] = index + 1
        turn = script[-1] if index >= len(script) else script[index]
        return turn


def candidate_marker(source):
    return f"GEMMA_LAB_CANDIDATE={Path(source).name}"


def apply_tool_calls(root, turn):
    """Apply edit_file calls from one assistant turn onto a working tree."""
    root = Path(root)
    applied = []
    for call in turn.get("tool_calls") or []:
        function = call.get("function") or {}
        if function.get("name") != "edit_file":
            continue
        arguments = function.get("arguments") or "{}"
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        relative = arguments["filepath"]
        path = root / relative
        text = path.read_text()
        old, new = arguments["old_string"], arguments["new_string"]
        if old not in text:
            raise ValueError(f"{relative} does not contain the requested text")
        path.write_text(text.replace(old, new, 1))
        applied.append(relative)
    return applied


class StubModelServer:
    """Tiny ``/v1/chat/completions`` server plus ``/health`` and ``/metrics``."""

    def __init__(self, responder, host="127.0.0.1", port=0):
        self.responder = responder
        self.host = host
        self.port = port
        self.prefix_hits = 0
        self.prefix_queries = 0
        self._httpd = None
        self._thread = None

    def start(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return

            def _send(self, code, body, content_type):
                payload = body if isinstance(body, bytes) else body.encode()
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _json(self, code, payload):
                self._send(code, json.dumps(payload), "application/json")

            def do_GET(self):
                path = self.path.split("?", 1)[0]
                if path == "/health":
                    self._json(200, {"status": "ok"})
                elif path == "/metrics":
                    text = (
                        "# TYPE vllm:prefix_cache_hits_total counter\n"
                        f"vllm:prefix_cache_hits_total {owner.prefix_hits}\n"
                        f"vllm:prefix_cache_queries_total {owner.prefix_queries}\n"
                    )
                    self._send(200, text, "text/plain; version=0.0.4")
                elif path == "/v1/models":
                    self._json(200, {"object": "list", "data": [{"id": "stub-model"}]})
                else:
                    self._json(404, {"error": "not found"})

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                request = json.loads(raw.decode() or "{}")
                path = self.path.split("?", 1)[0]
                if path != "/v1/chat/completions":
                    self._json(404, {"error": "not found"})
                    return
                owner.prefix_queries += 1
                owner.prefix_hits += 1
                turn = owner.responder(request)
                message = {"role": "assistant", "content": turn.get("content")}
                if turn.get("tool_calls"):
                    message["tool_calls"] = turn["tool_calls"]
                finish = "tool_calls" if turn.get("tool_calls") else "stop"
                self._json(
                    200,
                    {
                        "id": "chatcmpl-stub",
                        "object": "chat.completion",
                        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                        "usage": {
                            "prompt_tokens": 8,
                            "completion_tokens": 4,
                            "total_tokens": 12,
                        },
                    },
                )

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def close(self):
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc, tb):
        self.close()

    @property
    def base_url(self):
        return f"http://{self.host}:{self.port}"

    @property
    def openai_base_url(self):
        return self.base_url + "/v1"


def smoke_server_for_candidate(source, behavior="repair"):
    """Start a server whose script is selected by this candidate's marker.

    Put ``candidate_marker(source)`` in the system prompt. ``behavior`` is
    ``repair`` (edit then submit) or ``empty`` (submit with no edit).
    """
    marker = candidate_marker(source)
    turns = repair_turns() if behavior == "repair" else empty_submit_turns()
    server = StubModelServer(ScriptedResponder({marker: turns}))
    server.start()
    return server, marker
