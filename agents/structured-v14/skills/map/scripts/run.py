"""Zero-arg repo map. Prints paths and class or function signatures.

The subprocess sandbox rewrites /tmp and /workspace only inside command
strings. This script finds the repo from GEMMA_CHECK_ROOT, then /workspace,
then PYTHONPATH. It does not write files. Output order is sorted. Dotfiles,
vendored directories, and test-heavy directories are skipped. The text stops
at CHAR_BUDGET characters, about 3k tokens at 4 characters per token.
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

CHAR_BUDGET = 12000
MAX_FILE_BYTES = 512 * 1024
SKIP_DIRS = {
    "benchmark",
    "benchmarks",
    "build",
    "dist",
    "dist-packages",
    "doc",
    "docs",
    "docs_src",
    "example",
    "examples",
    "tutorial",
    "tutorials",
    "htmlcov",
    "node_modules",
    "site-packages",
    "test",
    "testing",
    "tests",
    "third_party",
    "thirdparty",
    "vendor",
    "vendored",
    "vendors",
    "venv",
    "__pycache__",
}


def root():
    candidates = [os.environ.get("GEMMA_CHECK_ROOT"), "/workspace"]
    candidates.extend(os.environ.get("PYTHONPATH", "").split(os.pathsep))
    for cand in candidates:
        if cand and (Path(cand) / ".git").exists():
            return Path(cand)
    return Path("/workspace")


def _skip_dir(name):
    return name.startswith(".") or name in SKIP_DIRS or name.endswith(".egg-info")


def python_files(repo):
    found = []
    for folder, directories, filenames in os.walk(repo, followlinks=False):
        directories[:] = sorted(
            name
            for name in directories
            if not _skip_dir(name) and not (Path(folder) / name).is_symlink()
        )
        for name in filenames:
            if name.startswith(".") or not name.endswith(".py"):
                continue
            path = Path(folder) / name
            if path.is_symlink() or not path.is_file():
                continue
            found.append(path)
    found.sort(key=lambda path: path.relative_to(repo).as_posix())
    return found


def signatures(source):
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    names = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            names.append(node.name)
            for child in node.body:
                if isinstance(child, ast.AsyncFunctionDef):
                    names.append(f"async {node.name}.{child.name}")
                elif isinstance(child, ast.FunctionDef):
                    names.append(f"{node.name}.{child.name}")
        elif isinstance(node, ast.AsyncFunctionDef):
            names.append(f"async {node.name}")
        elif isinstance(node, ast.FunctionDef):
            names.append(node.name)
    return names


def _info(repo, path):
    relative = path.relative_to(repo).as_posix()
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return relative, ["[skipped large]"]
        text = path.read_text(errors="replace")
    except OSError:
        return relative, ["[unreadable]"]
    names = signatures(text)
    if names is None:
        return relative, ["[unparsed]"]
    return relative, names


def _header(files, shown, sigs, truncated):
    flag = 1 if truncated else 0
    return (
        f"map files={files} shown={shown} signatures={sigs} truncated={flag} budget={CHAR_BUDGET}"
    )


def _compose(infos, chosen, total, truncated):
    lines = []
    sigs = 0
    for (relative, _names), picked in zip(infos, chosen, strict=True):
        visible = [name for name in picked if not name.startswith("[")]
        sigs += len(visible)
        if picked:
            lines.append(relative + ": " + ", ".join(picked))
        else:
            lines.append(relative + ":")
    header = _header(total, len(infos), sigs, truncated)
    if not lines:
        return header
    return header + "\n" + "\n".join(lines)


def render(repo):
    infos = [_info(repo, path) for path in python_files(repo)]
    total = len(infos)
    shown = total
    while shown >= 0:
        text = _compose(infos[:shown], [[] for _item in range(shown)], total, shown < total)
        if len(text) <= CHAR_BUDGET:
            break
        shown -= 1
    if shown <= 0:
        return _header(total, 0, 0, total > 0)[:CHAR_BUDGET]
    truncated = shown < total
    chosen = [[] for _item in range(shown)]
    for index in range(shown):
        for name in infos[index][1]:
            chosen[index].append(name)
            text = _compose(infos[:shown], chosen, total, truncated)
            if len(text) > CHAR_BUDGET:
                chosen[index].pop()
                return _compose(infos[:shown], chosen, total, True)
    return _compose(infos[:shown], chosen, total, truncated)


def main(argv=None):
    list(sys.argv[1:] if argv is None else argv)
    print(render(root()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
