import ast
import builtins
import json
import shutil
import sys
import warnings
from pathlib import Path

import pytest

from gemma_lab.notebook import _BUDGET_HARDCODE, generate, generate_pair
from gemma_lab.paired import assert_adk_submission_version

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE = REPO_ROOT / "agents" / "baseline"
OFFICIAL_CODES = REPO_ROOT / "tests" / "fixtures" / "official_starter_codes.json"


def _starter(tmp_path, *, hardcode=False):
    root = tmp_path / "vendor/official/notebook"
    root.mkdir(parents=True)
    loop = _BUDGET_HARDCODE if hardcode else ""
    loop += (
        "SAMPLE_TASKS = tasks[:2]\n"
        "eval_config = EvalConfig(\n"
        "    submission_dir=AGENT_DIR,\n"
        "    results_dir=WORKING_DIR / 'results',\n"
        "    sandbox='subprocess',\n"
        ")\n"
        "for idx, task in enumerate(SAMPLE_TASKS):\n"
        "    pass\n"
        "submission_df = None\n"
    )
    codes = [
        "# Remove broken cutlass .pth hooks if present\n",
        "SAMPLE_SUBMISSION_SRC = None\n",
        "x = 2\n",
        "declared_model = validate_single_declared_model(AGENT_DIR)\n"
        "adapters = discover_adapters(str(AGENT_DIR), "
        "adapter_extensions=ALLOWED_ADAPTER_EXTENSIONS)\n"
        "server_instance.start()\n"
        "import torch\n"
        "tp_size = 4\n",
        loop,
        "zip_path = Path(shutil.make_archive(str(zip_base), 'zip', root_dir=AGENT_DIR))\n",
    ]
    cells = [{"cell_type": "code", "source": [code]} for code in codes]
    notebook = root / "getting-started-gemma-4-developer-agent.ipynb"
    notebook.write_text(json.dumps({"cells": cells}))
    (root / "kernel-metadata.json").write_text(
        json.dumps(
            {
                "id_no": 123,
                "dataset_sources": ["metric/gemma-4-developer-agent-wheelhouse"],
                "competition_sources": ["gemma-4-developer-agent"],
                "model_sources": ["official/model/2"],
            }
        )
    )


def _arms(tmp_path):
    left = tmp_path / "arm-a"
    right = tmp_path / "arm-b"
    shutil.copytree(BASELINE, left)
    shutil.copytree(BASELINE, right)
    (right / "prompts" / "system.md").write_text("arm b prompt\n")
    budget = (
        "evaluation:\n"
        "  timeout_seconds: 300\n"
        "  max_tool_calls: 37\n"
        "  max_time_minutes: 7.5\n"
        "  max_turns: 41\n"
    )
    (left / "eval_config.yaml").write_text(budget)
    (right / "eval_config.yaml").write_text(budget)
    cohort = tmp_path / "cohort.json"
    cohort.write_text(json.dumps(["fastapi_11194"]))
    protocol = tmp_path / "protocol.yaml"
    protocol.write_text(
        "arms:\n"
        f"  A:\n    source: {left}\n"
        f"  B:\n    source: {right}\n"
        "allow_identical: false\n"
        "allowed_differences:\n"
        "  - prompts/*\n"
        "  - eval_config.yaml\n"
        "cohort:\n"
        f"  path: {cohort}\n"
        "repeats: 1\n"
        "order_rule: per_task_parity_v1\n"
        "pins_mode: record\n"
    )
    return protocol


def _budget_agent(tmp_path, calls=37, minutes=7.5):
    dest = tmp_path / "agent"
    shutil.copytree(BASELINE, dest)
    (dest / "eval_config.yaml").write_text(
        "evaluation:\n"
        "  timeout_seconds: 300\n"
        f"  max_tool_calls: {calls}\n"
        f"  max_time_minutes: {minutes}\n"
        "  max_turns: 41\n"
    )
    return dest


def _notebook_code(path):
    notebook = json.loads(path.read_text())
    cells = ["".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"]
    return notebook, "\n".join(cells), cells


def _bind_target(scope, node):
    if isinstance(node, ast.Name):
        scope.add(node.id)
    elif isinstance(node, (ast.Tuple, ast.List)):
        for elt in node.elts:
            _bind_target(scope, elt)
    elif isinstance(node, ast.Starred):
        _bind_target(scope, node.value)


def _collect_module_bindings(statements, scope):
    for node in statements:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            scope.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                scope.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    scope.add(alias.asname or alias.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                _bind_target(scope, target)
        elif isinstance(node, ast.AnnAssign):
            _bind_target(scope, node.target)
        elif isinstance(node, ast.AugAssign):
            _bind_target(scope, node.target)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            _bind_target(scope, node.target)
            _collect_module_bindings(node.body, scope)
            _collect_module_bindings(node.orelse, scope)
        elif isinstance(node, ast.While):
            _collect_module_bindings(node.body, scope)
            _collect_module_bindings(node.orelse, scope)
        elif isinstance(node, ast.If):
            _collect_module_bindings(node.body, scope)
            _collect_module_bindings(node.orelse, scope)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars:
                    _bind_target(scope, item.optional_vars)
            _collect_module_bindings(node.body, scope)
        elif isinstance(node, ast.Try):
            _collect_module_bindings(node.body, scope)
            for handler in node.handlers:
                if handler.name:
                    scope.add(handler.name)
                _collect_module_bindings(handler.body, scope)
            _collect_module_bindings(node.orelse, scope)
            _collect_module_bindings(node.finalbody, scope)


class _NameChecker(ast.NodeVisitor):
    def __init__(self, module_names):
        self.scopes = [set(module_names)]
        self.undefined = []

    def _lookup(self, name):
        if name in set(dir(builtins)) | {"display", "get_ipython"}:
            return True
        return any(name in scope for scope in self.scopes)

    def visit_FunctionDef(self, node):
        self.scopes[-1].add(node.name)
        local = {arg.arg for arg in node.args.args}
        local.update(arg.arg for arg in node.args.posonlyargs)
        local.update(arg.arg for arg in node.args.kwonlyargs)
        if node.args.vararg:
            local.add(node.args.vararg.arg)
        if node.args.kwarg:
            local.add(node.args.kwarg.arg)
        self.scopes.append(local)
        for stmt in node.body:
            self.visit(stmt)
        self.scopes.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node):
        local = {arg.arg for arg in node.args.args}
        local.update(arg.arg for arg in node.args.posonlyargs)
        local.update(arg.arg for arg in node.args.kwonlyargs)
        if node.args.vararg:
            local.add(node.args.vararg.arg)
        if node.args.kwarg:
            local.add(node.args.kwarg.arg)
        self.scopes.append(local)
        self.visit(node.body)
        self.scopes.pop()

    def visit_ClassDef(self, node):
        self.scopes[-1].add(node.name)
        self.scopes.append(set())
        for stmt in node.body:
            self.visit(stmt)
        self.scopes.pop()

    def visit_Import(self, node):
        for alias in node.names:
            self.scopes[-1].add((alias.asname or alias.name).split(".")[0])

    def visit_ImportFrom(self, node):
        for alias in node.names:
            if alias.name != "*":
                self.scopes[-1].add(alias.asname or alias.name)

    def visit_Assign(self, node):
        for target in node.targets:
            _bind_target(self.scopes[-1], target)
        self.visit(node.value)

    def visit_AnnAssign(self, node):
        _bind_target(self.scopes[-1], node.target)
        if node.value is not None:
            self.visit(node.value)

    def visit_AugAssign(self, node):
        self.visit(node.target)
        _bind_target(self.scopes[-1], node.target)
        self.visit(node.value)

    def visit_NamedExpr(self, node):
        _bind_target(self.scopes[-1], node.target)
        self.visit(node.value)

    def visit_For(self, node):
        self.visit(node.iter)
        _bind_target(self.scopes[-1], node.target)
        for stmt in node.body:
            self.visit(stmt)
        for stmt in node.orelse:
            self.visit(stmt)

    visit_AsyncFor = visit_For

    def visit_With(self, node):
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars:
                _bind_target(self.scopes[-1], item.optional_vars)
        for stmt in node.body:
            self.visit(stmt)

    visit_AsyncWith = visit_With

    def visit_ExceptHandler(self, node):
        if node.type is not None:
            self.visit(node.type)
        if node.name:
            self.scopes[-1].add(node.name)
        for stmt in node.body:
            self.visit(stmt)

    def _visit_comprehension(self, node, emit):
        self.scopes.append(set())
        for generator in node.generators:
            self.visit(generator.iter)
            _bind_target(self.scopes[-1], generator.target)
            for test in generator.ifs:
                self.visit(test)
        emit()
        self.scopes.pop()

    def visit_ListComp(self, node):
        self._visit_comprehension(node, lambda: self.visit(node.elt))

    def visit_SetComp(self, node):
        self._visit_comprehension(node, lambda: self.visit(node.elt))

    def visit_GeneratorExp(self, node):
        self._visit_comprehension(node, lambda: self.visit(node.elt))

    def visit_DictComp(self, node):
        self._visit_comprehension(node, lambda: (self.visit(node.key), self.visit(node.value)))

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load) and not self._lookup(node.id):
            self.undefined.append(node.id)


def undefined_names(source):
    tree = ast.parse(source)
    module = set()
    _collect_module_bindings(tree.body, module)
    checker = _NameChecker(module)
    checker.visit(tree)
    return sorted(set(checker.undefined))


def test_single_arm_sets_caps_from_eval_config(tmp_path, monkeypatch):
    # max_tool_calls and max_time_minutes are now set explicitly from eval_config;
    # previously inherited from the fetched starter.
    _starter(tmp_path, hardcode=True)
    monkeypatch.chdir(tmp_path)
    agent = _budget_agent(tmp_path)
    output = tmp_path / "generated"
    generate(agent, "owner", "experiment-v1", output)
    _notebook, code, _cells = _notebook_code(output / "evaluation.ipynb")
    assert "max_tool_calls = 37\n" in code
    assert "max_time_minutes = 7.5\n" in code
    assert _BUDGET_HARDCODE not in code
    assert "assert_adk_submission_version" not in code
    assert "hashlib.sha256(payload)" in code


def test_pair_notebook_sets_configured_budgets_and_adk_floor(tmp_path, monkeypatch):
    _starter(tmp_path, hardcode=True)
    monkeypatch.chdir(tmp_path)
    protocol = _arms(tmp_path)
    output = tmp_path / "paired"
    generate_pair(protocol, "owner", "pair-v1", output)
    notebook = json.loads((output / "evaluation.ipynb").read_text())
    code = "\n".join(
        "".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"
    )
    assert "'max_tool_calls': 37" in code
    assert "'max_time_minutes': 7.5" in code
    assert "'max_turns': 41" in code
    assert "max_tool_calls = int(budgets['max_tool_calls'])" in code
    assert "max_time_minutes = float(budgets['max_time_minutes'])" in code
    assert "cap_seconds=450.0" in code
    assert "max_tool_calls = 100" not in code
    assert "max_time_minutes = 5.0" not in code
    assert "assert_adk_submission_version(_ADK_SUBMISSION_VERSION)" in code
    assert "'adk_submission_version': _ADK_SUBMISSION_VERSION" in code
    restart = code.split("def restart_model_server", 1)[1].split("def ", 1)[0]
    assert restart.index("session_pgid") < restart.index("server_instance.stop()")
    assert restart.index("server_instance.stop()") < restart.index("release_server_after_stop")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert_adk_submission_version("0.2.12")
    with pytest.warns(UserWarning, match="thinking_budget"):
        assert_adk_submission_version("0.2.11")
    with pytest.raises(RuntimeError, match=">=0.2.11") as raised:
        assert_adk_submission_version("0.2.10")
    assert "thinking_budget" not in str(raised.value)
    metadata = json.loads((output / "kernel-metadata.json").read_text())
    assert metadata["is_private"] is True
    assert metadata["enable_internet"] is False
    assert metadata["enable_gpu"] is True
    assert metadata["id"] == "owner/pair-v1"


def test_pair_starter_drift_fails_closed(tmp_path, monkeypatch):
    _starter(tmp_path, hardcode=True)
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "vendor/official/notebook/getting-started-gemma-4-developer-agent.ipynb"
    path.write_text(json.dumps({"cells": []}))
    with pytest.raises(ValueError, match="structure changed"):
        generate_pair(_arms(tmp_path), "owner", "pair-v1", tmp_path / "output")


def test_pair_schedule_cli_does_not_pack(tmp_path, monkeypatch, capsys):
    cohort = tmp_path / "cohort.json"
    cohort.write_text(json.dumps(["t1", "t2"]))
    protocol = tmp_path / "protocol.yaml"
    protocol.write_text(
        "arms:\n"
        "  A:\n    source: agents/missing-a\n"
        "  B:\n    source: agents/missing-b\n"
        "cohort:\n"
        f"  path: {cohort}\n"
        "repeats: 2\n"
        "order_rule: per_task_parity_v1\n"
    )
    destination = tmp_path / "schedule.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gemma-lab",
            "pair-schedule",
            "--protocol",
            str(protocol),
            "--output",
            str(destination),
        ],
    )
    from gemma_lab.cli import main

    main()
    saved = json.loads(destination.read_text())
    assert saved["rule"] == "per_task_parity_v1"
    assert len(saved["entries"]) == 4
    printed = json.loads(capsys.readouterr().out)
    assert printed["schedule_sha256"] == saved["schedule_sha256"]


def _write_kernel(root):
    (root / "kernel-metadata.json").write_text(
        json.dumps(
            {
                "id_no": 123,
                "dataset_sources": ["metric/gemma-4-developer-agent-wheelhouse"],
                "competition_sources": ["gemma-4-developer-agent"],
                "model_sources": ["official/model/2"],
            }
        )
    )


def _official_starter(tmp_path, *, live_caps=False):
    root = tmp_path / "vendor/official/notebook"
    root.mkdir(parents=True)
    cells = json.loads(OFFICIAL_CODES.read_text())["cells"]
    if live_caps:
        cells[4] = cells[4].replace(
            _BUDGET_HARDCODE,
            "max_tool_calls = int(eval_section.get('max_tool_calls', 100))\n"
            "max_time_minutes = float(eval_section.get('max_time_minutes', 5.0))\n",
        )
    notebook = root / "getting-started-gemma-4-developer-agent.ipynb"
    notebook.write_text(
        json.dumps({"cells": [{"cell_type": "code", "source": [code]} for code in cells]})
    )
    _write_kernel(root)


def _eval_cell(cells):
    matches = [cell for cell in cells if "def make_evaluator" in cell]
    assert len(matches) == 1
    return matches[0]


def test_official_starter_pair_has_no_undefined_names(tmp_path, monkeypatch):
    _official_starter(tmp_path)
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "paired"
    generate_pair(_arms(tmp_path), "owner", "pair-v1", output)
    _notebook, code, cells = _notebook_code(output / "evaluation.ipynb")
    eval_cell = _eval_cell(cells)
    assert "AGENT_DIR" not in eval_cell
    assert "eval_config_file" not in eval_cell
    assert "max_tool_calls = int(budgets['max_tool_calls'])" in eval_cell
    assert "max_time_minutes = float(budgets['max_time_minutes'])" in eval_cell
    assert undefined_names(code) == []


def test_live_eval_config_reads_still_set_per_arm_caps(tmp_path, monkeypatch):
    _official_starter(tmp_path, live_caps=True)
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "paired"
    generate_pair(_arms(tmp_path), "owner", "pair-v1", output)
    _notebook, code, cells = _notebook_code(output / "evaluation.ipynb")
    eval_cell = _eval_cell(cells)
    assert "AGENT_DIR" not in eval_cell
    assert "eval_section.get('max_tool_calls'" not in eval_cell
    assert "max_tool_calls = int(budgets['max_tool_calls'])" in eval_cell
    assert undefined_names(code) == []
    single = tmp_path / "single"
    generate(_budget_agent(tmp_path), "owner", "experiment-v1", single)
    _notebook, single_code, _cells = _notebook_code(single / "evaluation.ipynb")
    assert "max_tool_calls = 37\n" in single_code
    assert "max_time_minutes = 7.5\n" in single_code
    assert "eval_section.get('max_tool_calls'" not in single_code
    assert "timeout_seconds = int(eval_section.get('timeout_seconds', 300))" in single_code
    assert undefined_names(single_code) == []


def test_unrecognized_cap_assignment_fails_closed(tmp_path, monkeypatch):
    _starter(tmp_path, hardcode=False)
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "vendor/official/notebook/getting-started-gemma-4-developer-agent.ipynb"
    notebook = json.loads(path.read_text())
    source = "".join(notebook["cells"][4]["source"])
    notebook["cells"][4]["source"] = ["max_tool_calls = 99\n" + source]
    path.write_text(json.dumps(notebook))
    with pytest.raises(ValueError, match="unrecognized"):
        generate(_budget_agent(tmp_path), "owner", "experiment-v1", tmp_path / "output")
