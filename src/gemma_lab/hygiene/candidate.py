"""Static candidate lint (G0) and synthetic skill-audit replay (G2).

G2 does not modify the candidate. A miss on the paths the in-agent audit already
claims to flag is a BLOCK. Nested `pkg/tests/` missed by that audit is also a
BLOCK. Other grading-reset paths the audit misses are WARN.
"""

import importlib.util
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from gemma_lab.bundle import load_yaml
from gemma_lab.hygiene.errors import HygieneInputError
from gemma_lab.hygiene.rules import finding

HANDOFF = re.compile(r"By\s+(\d+)\s+elapsed seconds")
REQUIRED_AUDIT_PATHS = {"repro.py", "tests/test_pkg.py", "conftest.py"}
NESTED_TEST = "pkg/tests/test_nested.py"
GRADING_GAP_PATHS = (
    ".pytest.ini",
    "pkg/foo_test.py",
    "sitecustomize.py",
    "testing/helper.py",
    "tox.ini",
)


def lint_tree(source: Path, policy: dict) -> list[dict]:
    source = Path(source)
    if not (source / "agent.yaml").is_file():
        raise HygieneInputError(f"agent.yaml is missing: {source}")
    roles = _roles(source)
    found = _g0(source, roles, policy)
    found.extend(_g2(source))
    return found


def _g0(source: Path, roles: list[dict], policy: dict) -> list[dict]:
    found = []
    if not roles:
        found.append(
            finding("G0.missing_submit", "block", evidence="no LlmAgent role declares tools")
        )
        return found
    for index, role in enumerate(roles):
        names = _tool_names(role)
        final = index == len(roles) - 1
        if "write_file" in names:
            found.append(
                finding(
                    "G0.write_file",
                    "block",
                    path=str(role.get("name") or index),
                    evidence="write_file is granted",
                )
            )
        if final and "submit_patch" not in names:
            found.append(
                finding(
                    "G0.missing_submit",
                    "block",
                    path=str(role.get("name") or index),
                    evidence="final role has no submit_patch",
                )
            )
        if not final and "submit_patch" in names:
            found.append(
                finding(
                    "G0.early_submit",
                    "block",
                    path=str(role.get("name") or index),
                    evidence="a non-final role has submit_patch",
                )
            )
        for skill in role.get("skills") or []:
            if not (source / skill / "SKILL.md").is_file():
                found.append(
                    finding(
                        "G0.missing_skill",
                        "block",
                        path=str(skill),
                        evidence="skill manifest missing",
                    )
                )
    prompts = [
        role.get("instruction") if isinstance(role.get("instruction"), str) else ""
        for role in roles
    ]
    if not any("/tmp" in text for text in prompts):
        found.append(
            finding(
                "G0.scratch_clause",
                "warn",
                evidence="no role prompt tells the model to keep scratch under /tmp",
                confidence="heuristic",
            )
        )
    if "submit_patch" not in prompts[-1]:
        found.append(
            finding(
                "G0.submit_clause",
                "warn",
                path=str(roles[-1].get("name") or ""),
                evidence="final prompt does not mention submit_patch",
                confidence="heuristic",
            )
        )
    found.extend(_handoff(source, prompts, policy))
    return found


def _handoff(source: Path, prompts: list[str], policy: dict) -> list[dict]:
    match = HANDOFF.search("\n".join(prompts))
    if not match:
        return []
    minutes = _max_time_minutes(source)
    if minutes <= 0:
        return []
    seconds = int(match.group(1))
    fraction = float(policy.get("handoff_fraction", 0.6))
    if seconds / (minutes * 60) < fraction:
        return []
    return [
        finding(
            "G0.handoff_ratio",
            "warn",
            evidence=(
                f"handoff at {seconds}s is {seconds / (minutes * 60):.0%}"
                f" of the {minutes:g} min budget"
            ),
            confidence="heuristic",
        )
    ]


def _g2(source: Path) -> list[dict]:
    script = source / "skills/verify-patch/scripts/check.py"
    if not script.is_file():
        return []
    try:
        flagged = _audit_fixture(script)
    except (OSError, ValueError, subprocess.TimeoutExpired, AttributeError) as exc:
        return [finding("G2.error", "block", evidence=str(exc))]
    missing = sorted(REQUIRED_AUDIT_PATHS - flagged)
    found = []
    if missing:
        found.append(
            finding(
                "G2.divergence",
                "block",
                evidence="in-agent audit missed " + ",".join(missing),
            )
        )
    if NESTED_TEST not in flagged:
        found.append(
            finding(
                "G2.superset",
                "block",
                path=NESTED_TEST,
                evidence="in-agent audit missed nested tests/ that grading resets",
            )
        )
    for path in GRADING_GAP_PATHS:
        if path not in flagged:
            found.append(
                finding(
                    "G2.grading_gap",
                    "warn",
                    path=path,
                    evidence="in-agent audit missed a path grading resets",
                )
            )
    return found


def _audit_fixture(script: Path) -> set[str]:
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        (root / "pkg").mkdir()
        (root / "pkg/__init__.py").write_text("VALUE = 1\n")
        (root / "pkg/tests").mkdir()
        (root / "pkg/tests/test_nested.py").write_text("def test_nested():\n    assert True\n")
        (root / "pkg/foo_test.py").write_text("def test_foo():\n    assert True\n")
        (root / "testing").mkdir()
        (root / "testing/helper.py").write_text("HELPER = 1\n")
        (root / "tests").mkdir()
        (root / "tests/test_pkg.py").write_text("def test_value():\n    assert True\n")
        (root / "conftest.py").write_text("# baseline\n")
        (root / ".pytest.ini").write_text("[pytest]\n")
        (root / "tox.ini").write_text("[tox]\n")
        (root / "sitecustomize.py").write_text("# site\n")
        _git(root, "init", "-q")
        _git(root, "config", "user.name", "Hygiene fixture")
        _git(root, "config", "user.email", "hygiene@example.test")
        _git(root, "add", ".")
        _git(root, "commit", "-qm", "baseline")
        (root / "tests/test_pkg.py").write_text("def test_value():\n    assert False\n")
        (root / "conftest.py").write_text("# edited\n")
        (root / "pkg/tests/test_nested.py").write_text("def test_nested():\n    assert False\n")
        (root / "pkg/foo_test.py").write_text("def test_foo():\n    assert False\n")
        (root / "testing/helper.py").write_text("HELPER = 2\n")
        (root / ".pytest.ini").write_text("[pytest]\naddopts = -q\n")
        (root / "tox.ini").write_text("[tox]\nenvlist = py\n")
        (root / "sitecustomize.py").write_text("# edited\n")
        (root / "repro.py").write_text("print('debug')\n")
        module = _load(script)
        result = module.audit(root)
        return set(result.get("untracked") or []) | set(result.get("forbidden") or [])


def _load(script: Path):
    spec = importlib.util.spec_from_file_location(f"hygiene_g2_{script.stat().st_ino}", script)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load {script}")
    module = importlib.util.module_from_spec(spec)
    prior = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = prior
    return module


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True, timeout=30)


def _roles(source: Path) -> list[dict]:
    roles: list[dict] = []
    root = load_yaml(source / "agent.yaml", source)
    _collect(root, source, source, roles)
    return roles


def _collect(node, base: Path, source: Path, roles: list[dict]) -> None:
    if not isinstance(node, dict):
        return
    children = node.get("sub_agents")
    agent_class = node.get("agent_class")
    if children and agent_class in {None, "SequentialAgent", "ParallelAgent", "LoopAgent"}:
        for child in children:
            if isinstance(child, dict) and child.get("config_path"):
                target = (base / child["config_path"]).resolve()
                _collect(load_yaml(target, source), target.parent, source, roles)
            else:
                _collect(child, base, source, roles)
        return
    if node.get("model") or agent_class == "LlmAgent" or "tools" in node or "instruction" in node:
        roles.append(node)


def _tool_names(role: dict) -> list[str]:
    names = []
    for tool in role.get("tools") or []:
        if isinstance(tool, str):
            names.append(tool)
        elif isinstance(tool, dict):
            if "agent_tool" in tool:
                names.append("agent_tool")
            elif tool.get("name"):
                names.append(str(tool["name"]))
    return names


def _max_time_minutes(source: Path) -> float:
    path = source / "eval_config.yaml"
    if not path.is_file():
        return 0
    loaded = yaml.safe_load(path.read_text()) or {}
    if not isinstance(loaded, dict):
        return 0
    section = loaded.get("evaluation", loaded)
    if not isinstance(section, dict):
        return 0
    try:
        return float(section.get("max_time_minutes") or 0)
    except (TypeError, ValueError):
        return 0
