"""Patch hygiene rules H1, H2, H3, H4, H5, and H8.

Severities follow the coordinator override where it differs from the design spec.
See the module docstring on `audit_files` for those choices.
"""

import io
import re
import tokenize
from fnmatch import fnmatch
from pathlib import PurePosixPath

from gemma_lab.hygiene.diffparse import FileDiff
from gemma_lab.hygiene.trace import ToolEvent, TraceView

VERIFIERS = {"verify", "verifier"}
DEBUGGERS = {"pdb", "ipdb", "pudb"}
PATH_HACKS = {("sys", "path", "insert"), ("sys", "path", "append"), ("sys", "path", "extend")}
HOST_IMPORT = re.compile(r"/site-packages/\S+")
METADATA = re.compile(
    r"\bpip3?\s+(show|list|freeze)\b"
    r"|\bpython3?\s+-m\s+pip\s+(show|list|freeze)\b"
    r"|importlib\.metadata\.version\b"
    r"|\bimportlib\.metadata\b"
    r"|\bpkg_resources\b"
)
PROTECTED_FILES = {"pytest.ini", ".pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini"}
IMPORT_HOOKS = {"sitecustomize.py", "usercustomize.py", "_swegemma_stubs.py"}
PACKAGING_FILES = {"noxfile.py", "setup.py"}
EDIT_AFTER_SUBMIT = {"edit_file", "write_file", "run_command"}


def finding(rule, severity, path="", line=None, evidence="", confidence="high", **extra):
    item = {
        "rule": rule,
        "severity": severity,
        "path": path or "",
        "confidence": confidence,
        "evidence": " ".join(str(evidence).split())[:120],
    }
    if line is not None:
        item["line"] = line
    item.update(extra)
    return item


def sort_findings(items):
    return sorted(
        items,
        key=lambda item: (
            item["rule"],
            item.get("path") or "",
            item.get("line") or 0,
            item.get("evidence") or "",
        ),
    )


def audit_files(files: list[FileDiff], events: list[ToolEvent], policy: dict) -> list[dict]:
    """Return findings for one patch.

    Coordinator overrides applied here:
    - H2 blocks the grading reset set: nested conftest.py, test_*.py, *_test.py,
      pytest.ini, .pytest.ini, pyproject.toml, setup.cfg, tox.ini, every file under
      tests/ or test/, and .py files under testing/. Directory names are matched
      case-insensitively. noxfile.py and setup.py are WARN H8, not a block.
    - H5a blocks site-packages, `.venv`, and `build/lib` paths, sys.path hacks, and
      import hooks grading resets (*.pth, sitecustomize.py, usercustomize.py,
      _swegemma_stubs.py). Plain `venv/`, dist-packages, PYTHONPATH, and
      importlib.reload are not H5a path blocks.
    - H5b is warn on the task and marks the check invalid as behavior evidence.
    - H5c and H5d are warn. Run-level rates are applied by the run report, not here.
    - H3 does not block repeated submit_patch, a later get_status, or a non-verifier
      submit. An edit after the last submit is a warning. The count is info.
    """
    found = []
    found.extend(_h5a_import_hooks(files, policy))
    found.extend(_h1(files, events, policy))
    found.extend(_h2(files, policy))
    found.extend(_h8(files, policy))
    found.extend(_h4_and_h5a_lines(files, policy))
    found.extend(_h5a_paths(files, policy))
    found.extend(_h5_trace(events))
    return sort_findings(found)


def finalization(trace: TraceView, patch_text: str, *, trace_was_supplied: bool) -> dict:
    if not trace.recognized:
        return {
            "finalization": "unknown",
            "verifier_reached": None,
            "submit_calls": 0,
            "submitting_agents": [],
            "submit_is_last": None,
            "warn_unknown": trace_was_supplied and trace.schema == "unknown",
        }
    submits = [event for event in trace.events if event.tool == "submit_patch"]
    last_submit = None
    for index, event in enumerate(trace.events):
        if event.tool == "submit_patch":
            last_submit = index
    edit_after = False
    if last_submit is not None:
        edit_after = any(
            event.tool in EDIT_AFTER_SUBMIT for event in trace.events[last_submit + 1 :]
        )
    if submits:
        state = "explicit"
    elif patch_text.strip():
        state = "fallback"
    else:
        state = "none"
    verifier_author = any(event.agent in VERIFIERS for event in trace.events)
    return {
        "finalization": state,
        "verifier_reached": True if verifier_author else None,
        "submit_calls": len(submits),
        "submitting_agents": [event.agent for event in submits],
        "edit_after_submit": edit_after,
        "warn_unknown": False,
    }


def finalization_findings(info: dict) -> list[dict]:
    found = []
    if info["warn_unknown"]:
        found.append(
            finding(
                "H3.unknown",
                "warn",
                evidence="trace schema unrecognized; finalization was not inferred from the patch",
                confidence="heuristic",
            )
        )
    if info["finalization"] == "fallback":
        found.append(
            finding(
                "H3.fallback", "warn", evidence="no submit_patch call; patch is a fallback diff"
            )
        )
    if info["submit_calls"] > 1:
        found.append(
            finding(
                "H3.submit_count",
                "info",
                evidence=f"submit_patch called {info['submit_calls']} times",
            )
        )
    if info.get("edit_after_submit"):
        found.append(
            finding(
                "H3.edit_after_submit",
                "warn",
                evidence=(
                    "edits after the last submit_patch are discarded by the harness"
                    " (agent_runner.py:758)"
                ),
            )
        )
    return found


def _h1(files, events, policy) -> list[dict]:
    found = []
    for parsed in files:
        if not parsed.added or parsed.deleted or not parsed.path or _allowed(parsed.path, policy):
            continue
        path = parsed.path
        if _is_scratch(path):
            found.append(
                finding("H1.scratch", "block", path, evidence="known scratch or artifact path")
            )
            continue
        if parsed.new_mode == "120000":
            found.append(finding("H1.symlink", "block", path, evidence="new file mode 120000"))
            continue
        if parsed.binary:
            found.append(finding("H1.binary", "block", path, evidence="binary file added"))
            continue
        if _is_import_hook(path) or _is_protected(path):
            continue
        if _explained_new_file(path, files, events):
            found.append(
                finding(
                    "H1.explained",
                    "info",
                    path,
                    evidence=(
                        "new module imported by another changed file"
                        " and written with edit_file or write_file"
                    ),
                    confidence="heuristic",
                )
            )
        else:
            found.append(
                finding(
                    "H1.unexplained",
                    "warn",
                    path,
                    evidence=(
                        "new file is not a known scratch name and is not explained by an import"
                    ),
                    confidence="heuristic",
                )
            )
    return found


def _h5a_import_hooks(files, policy) -> list[dict]:
    found = []
    seen = set()
    for parsed in files:
        for path in (parsed.old_path, parsed.new_path):
            if not path or path in seen or _allowed(path, policy) or not _is_import_hook(path):
                continue
            seen.add(path)
            found.append(
                finding(
                    "H5a.import_hook",
                    "block",
                    path,
                    evidence=("grading resets import hooks (verification.py:64-76,396-402)"),
                )
            )
    return found


def _h8(files, policy) -> list[dict]:
    found = []
    seen = set()
    for parsed in files:
        for path in (parsed.old_path, parsed.new_path):
            name = PurePosixPath(path).name if path else ""
            if not path or path in seen or _allowed(path, policy) or name not in PACKAGING_FILES:
                continue
            seen.add(path)
            found.append(
                finding(
                    "H8.packaging",
                    "warn",
                    path,
                    evidence="not reset by grading; review",
                )
            )
    return found


def _h2(files, policy) -> list[dict]:
    found = []
    seen = set()
    for parsed in files:
        for path in (parsed.old_path, parsed.new_path):
            if not path or path in seen or _allowed(path, policy) or not _is_protected(path):
                continue
            seen.add(path)
            found.append(
                finding(
                    "H2.protected", "block", path, evidence="edit touches the grading protected set"
                )
            )
    return found


def _h5a_paths(files, policy) -> list[dict]:
    found = []
    seen = set()
    for parsed in files:
        for path in (parsed.old_path, parsed.new_path):
            if not path or path in seen or _allowed(path, policy) or not _is_h5a_path(path):
                continue
            seen.add(path)
            found.append(
                finding(
                    "H5a.path",
                    "block",
                    path,
                    evidence="path is under site-packages, .venv, or build/lib",
                )
            )
    return found


def _h4_and_h5a_lines(files, policy) -> list[dict]:
    found = []
    for parsed in files:
        if not parsed.path.endswith(".py") or _allowed(parsed.path, policy):
            continue
        print_allowed = _print_allowed(parsed.path, policy)
        lines = list(parsed.added_lines())
        imported_path = any(_imports_sys_path(_lex(text)) for _, text in lines)
        for line_no, text in lines:
            tokens = _lex(text)
            if _is_debugger(tokens):
                found.append(
                    finding("H4.debug", "block", parsed.path, line_no, evidence=text.strip())
                )
            elif not print_allowed and _bare_print(tokens):
                found.append(
                    finding(
                        "H4.print",
                        "warn",
                        parsed.path,
                        line_no,
                        evidence=text.strip(),
                        confidence="heuristic",
                    )
                )
            if _sys_path_hack(tokens, imported_sys_path=imported_path):
                found.append(
                    finding("H5a.sys_path", "block", parsed.path, line_no, evidence=text.strip())
                )
    return found


def _h5_trace(events: list[ToolEvent]) -> list[dict]:
    found = []
    for event in events:
        command = _command_text(event.args) if event.tool == "run_command" else ""
        if command and METADATA.search(command):
            found.append(
                finding(
                    "H5c.host_metadata",
                    "warn",
                    evidence=command.strip(),
                    confidence="heuristic",
                )
            )
        for flag in _isolated_flags(command):
            found.append(
                finding(
                    "H5d.python_flags",
                    "warn",
                    evidence=flag,
                    confidence="heuristic",
                )
            )
        match = HOST_IMPORT.search(event.output or "")
        if match:
            found.append(
                finding(
                    "H5b.host_import",
                    "warn",
                    evidence=match.group(0),
                    confidence="high",
                    evidence_blocked=True,
                )
            )
    return found


def _is_import_hook(path: str) -> bool:
    name = PurePosixPath(path).name
    return name in IMPORT_HOOKS or name.endswith(".pth")


def _is_protected(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if not parts:
        return False
    name = parts[-1]
    if name == "conftest.py" or name in PROTECTED_FILES:
        return True
    if name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py")):
        return True
    directories = [part.lower() for part in parts[:-1]]
    if any(part in {"tests", "test"} for part in directories):
        return True
    return name.endswith(".py") and any(part == "testing" for part in directories)


def _is_h5a_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if "site-packages" in parts or ".venv" in parts:
        return True
    return any(
        parts[index] == "build" and parts[index + 1] == "lib" for index in range(len(parts) - 1)
    )


def _is_scratch(path: str) -> bool:
    pure = PurePosixPath(path)
    name = pure.name
    if any(part in {"__pycache__", ".pytest_cache"} for part in pure.parts):
        return True
    if any(part.endswith(".egg-info") for part in pure.parts):
        return True
    if re.search(r"\.(orig|rej|bak|swp|log|pyc)$", name) or name == "nohup.out":
        return True
    if re.search(r"^\.adk_exec_.*\.py$", name):
        return True
    if re.search(r"^gemma-agent-repro.*\.py$", name) or name in {
        "gemma-agent-probe.py",
        "gemma-agent-checks.json",
    }:
        return True
    if len(pure.parts) != 1:
        return False
    return bool(
        re.search(
            r"^(repro.*\.py|reproduce.*\.py|.*_repro\.py|comprehensive_repro\.py|"
            r"debug.*\.py|scratch.*|tmp.*|test_issue.*\.py|test_fix.*\.py|"
            r"check_.*\.py|verify_.*\.py|notes.*\.md|requirements.*\.txt)$",
            name,
        )
    )


def _explained_new_file(path: str, files: list[FileDiff], events: list[ToolEvent]) -> bool:
    if len(PurePosixPath(path).parts) < 2 or not path.endswith(".py"):
        return False
    if not _imported(path, files) or not _written_by_edit(path, events):
        return False
    return True


def _imported(path: str, files: list[FileDiff]) -> bool:
    module = path[:-3].replace("/", ".")
    stem = PurePosixPath(path).stem
    names = {module, stem}
    if module.startswith("src."):
        names.add(module[4:])
    blob = "\n".join(
        line for parsed in files if parsed.path != path for _, line in parsed.added_lines()
    )
    for name in names:
        if re.search(rf"\b(?:import|from)\s+{re.escape(name)}\b", blob):
            return True
        if re.search(rf"\bimport\s+{re.escape(stem)}\b", blob):
            return True
    return False


def _written_by_edit(path: str, events: list[ToolEvent]) -> bool:
    for event in events:
        if event.tool not in {"edit_file", "write_file"}:
            continue
        args = event.args if isinstance(event.args, dict) else {}
        for key in ("path", "filepath", "file_path", "filename"):
            value = str(args.get(key, "")).replace("\\", "/").lstrip("./")
            if value == path:
                return True
    return False


def _is_debugger(tokens) -> bool:
    calls = _calls(tokens)
    if any(chain in {("breakpoint",), ("builtins", "breakpoint")} for chain in calls):
        return True
    if ("code", "interact") in calls:
        return True
    if any(
        chain[:2] == ("pdb", "set_trace") or chain[:2] == ("ipdb", "set_trace")
        for chain in _calls(tokens)
    ):
        return True
    if ("pudb", "set_trace") in _calls(tokens):
        return True
    if _imports_debugger(tokens) or _dynamic_debugger_import(tokens):
        return True
    return False


def _bare_print(tokens) -> bool:
    return ("print",) in _calls(tokens)


def _sys_path_hack(tokens, *, imported_sys_path=False) -> bool:
    calls = _calls(tokens)
    if any(call in PATH_HACKS or call == ("site", "addsitedir") for call in calls):
        return True
    for index in range(len(tokens) - 2):
        if tokens[index : index + 3] == [
            (tokenize.NAME, "sys"),
            (tokenize.OP, "."),
            (tokenize.NAME, "path"),
        ] and _assigns(tokens, index + 2):
            return True
    if not imported_sys_path and not _imports_sys_path(tokens):
        return False
    if any(call in {("path", "insert"), ("path", "append"), ("path", "extend")} for call in calls):
        return True
    for index, token in enumerate(tokens):
        if token != (tokenize.NAME, "path"):
            continue
        if index > 0 and tokens[index - 1] == (tokenize.OP, "."):
            continue
        if _assigns(tokens, index):
            return True
    return False


def _assigns(tokens, index) -> bool:
    cursor = _after_subscript(tokens, index + 1)
    return (
        cursor < len(tokens)
        and tokens[cursor][0] == tokenize.OP
        and tokens[cursor][1] in {"=", "+="}
    )


def _after_subscript(tokens, index) -> int:
    if index >= len(tokens) or tokens[index] != (tokenize.OP, "["):
        return index
    depth = 0
    while index < len(tokens):
        if tokens[index] == (tokenize.OP, "["):
            depth += 1
        elif tokens[index] == (tokenize.OP, "]"):
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return index


def _imports_sys_path(tokens) -> bool:
    for index, (_, value) in enumerate(tokens):
        if value != "from":
            continue
        window = [token[1] for token in tokens[index : index + 4]]
        if window == ["from", "sys", "import", "path"]:
            return True
    return False


def _calls(tokens) -> list[tuple[str, ...]]:
    calls = []
    index = 0
    while index < len(tokens):
        if tokens[index][0] != tokenize.NAME:
            index += 1
            continue
        if index > 0 and tokens[index - 1][1] in {"def", "class"}:
            index += 1
            continue
        chain = [tokens[index][1]]
        cursor = index + 1
        while (
            cursor + 1 < len(tokens)
            and tokens[cursor] == (tokenize.OP, ".")
            and tokens[cursor + 1][0] == tokenize.NAME
        ):
            chain.append(tokens[cursor + 1][1])
            cursor += 2
        if cursor < len(tokens) and tokens[cursor] == (tokenize.OP, "("):
            calls.append(tuple(chain))
            index = cursor + 1
            continue
        index += 1
    return calls


def _imports_debugger(tokens) -> bool:
    index = 0
    while index < len(tokens):
        kind, value = tokens[index]
        if kind == tokenize.NAME and value == "import":
            cursor = index + 1
            while cursor < len(tokens) and tokens[cursor][0] == tokenize.NAME:
                if tokens[cursor][1] in DEBUGGERS:
                    return True
                cursor += 1
                if cursor < len(tokens) and tokens[cursor] == (tokenize.OP, ","):
                    cursor += 1
        if (
            kind == tokenize.NAME
            and value == "from"
            and index + 1 < len(tokens)
            and tokens[index + 1][1] in DEBUGGERS
        ):
            return True
        index += 1
    return False


def _dynamic_debugger_import(tokens) -> bool:
    for index, (kind, value) in enumerate(tokens):
        if kind != tokenize.NAME or value not in {"__import__", "import_module"}:
            continue
        if value == "import_module":
            if (
                index < 2
                or tokens[index - 2] != (tokenize.NAME, "importlib")
                or tokens[index - 1] != (tokenize.OP, ".")
            ):
                continue
        argument = _call_string(tokens, index)
        if argument and any(name in argument for name in DEBUGGERS):
            return True
    return False


def _call_string(tokens, index) -> str:
    if index + 1 >= len(tokens) or tokens[index + 1] != (tokenize.OP, "("):
        return ""
    if index + 2 < len(tokens) and tokens[index + 2][0] == tokenize.STRING:
        return tokens[index + 2][1]
    return ""


def _lex(line: str):
    found = []
    try:
        generator = tokenize.generate_tokens(io.StringIO(line + "\n").readline)
        for token in generator:
            if token.type in {
                tokenize.ENCODING,
                tokenize.ENDMARKER,
                tokenize.NL,
                tokenize.NEWLINE,
                tokenize.COMMENT,
                tokenize.INDENT,
                tokenize.DEDENT,
            }:
                continue
            if (
                token.type == tokenize.STRING
                or token.type == tokenize.NAME
                or token.type == tokenize.OP
            ):
                found.append((token.type, token.string))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return found
    return found


def _command_text(args) -> str:
    if isinstance(args, str):
        return args
    if isinstance(args, dict):
        for key in ("command", "cmd", "script"):
            if key in args and args[key] is not None:
                return str(args[key])
    return ""


def _isolated_flags(command: str) -> list[str]:
    if not command:
        return []
    hits = []
    for token_index, token in enumerate(_shell_tokens(command)):
        if token not in {"python", "python3"}:
            continue
        flags = []
        for follow in _shell_tokens(command)[token_index + 1 :]:
            if not follow.startswith("-") or follow.startswith("--") or follow == "-":
                break
            flags.append(follow)
        for flag in flags:
            letters = flag[1:]
            if "I" in letters or "E" in letters:
                hits.append(token + " " + flag)
    return hits


def _shell_tokens(command: str) -> list[str]:
    tokens = []
    current = []
    quote = ""
    for char in command:
        if quote:
            if char == quote:
                quote = ""
            else:
                current.append(char)
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        if char.isspace() or char in {";", "|", "&"}:
            if current:
                tokens.append("".join(current))
                current = []
            continue
        current.append(char)
    if current:
        tokens.append("".join(current))
    return tokens


def _allowed(path: str, policy: dict) -> bool:
    return any(fnmatch(path, pattern) for pattern in policy.get("allow_paths") or [])


def _print_allowed(path: str, policy: dict) -> bool:
    return any(fnmatch(path, pattern) for pattern in policy.get("print_allowed_globs") or [])
