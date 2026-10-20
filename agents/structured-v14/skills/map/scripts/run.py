"""Zero-arg repo map. Prints a directory summary, then signatures.

The subprocess sandbox rewrites /tmp and /workspace only inside command
strings. This script finds the repo from GEMMA_CHECK_ROOT, then /workspace,
then PYTHONPATH. It does not write files. Output order is deterministic.
Dotfiles, vendored directories, site-packages, and node_modules are skipped.
Test, docs, build, and example directories are kept. Binary and large files
are counted and not parsed. The text stops at CHAR_BUDGET characters. The
walk stops near TIME_BUDGET seconds and still prints a partial summary.
"""

from __future__ import annotations

import ast
import os
import re
import sys
import time
from pathlib import Path

CHAR_BUDGET = 12000
TIME_BUDGET = 3.0
MAX_FILE_BYTES = 512 * 1024
PARSE_CAP = 400
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
SKIP_DIRS = {
    "__pycache__",
    "dist-packages",
    "node_modules",
    "site-packages",
    "third_party",
    "thirdparty",
    "vendor",
    "vendored",
    "vendors",
    "venv",
}
NOTE_TIME = "time budget reached; output is partial"
NOTE_ROLL = (
    "directory summary is rolled up to fit the budget; "
    "every visited file is counted in a printed directory"
)
NOTE_SIG = "directory summary covers the whole tree; signature lines are a subset"


def root():
    candidates = [os.environ.get("GEMMA_CHECK_ROOT"), "/workspace"]
    candidates.extend(os.environ.get("PYTHONPATH", "").split(os.pathsep))
    for cand in candidates:
        if cand and (Path(cand) / ".git").exists():
            return Path(cand)
    return Path("/workspace")


def _skip_dir(name):
    return name.startswith(".") or name in SKIP_DIRS or name.endswith(".egg-info")


def _keywords_from(value):
    if value is None:
        value = os.environ.get("GEMMA_MAP_KEYWORDS", "")
    if isinstance(value, str):
        return {item.lower() for item in IDENT.findall(value)}
    return {str(item).lower() for item in value if str(item).strip()}


def _path_tokens(path):
    return {item.lower() for item in re.split(r"[/_.]", path) if len(item) >= 3}


def _sig_tokens(names):
    found = set()
    for name in names:
        found.update(item.lower() for item in IDENT.findall(name))
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


def _read_signatures(path, size):
    if size > MAX_FILE_BYTES:
        return []
    try:
        data = path.read_bytes()
    except OSError:
        return []
    if b"\0" in data:
        return []
    names = signatures(data.decode(errors="replace"))
    if not names:
        return []
    return names


def _collect(repo, deadline, clock):
    direct = {}
    py_paths = []
    timed_out = False
    for folder, directories, filenames in os.walk(repo, followlinks=False):
        if clock() >= deadline:
            timed_out = True
            break
        directories[:] = sorted(
            name
            for name in directories
            if not _skip_dir(name) and not (Path(folder) / name).is_symlink()
        )
        relative = Path(folder).relative_to(repo).as_posix()
        key = "." if relative == "." else relative
        for name in sorted(filenames):
            if clock() >= deadline:
                timed_out = True
                break
            if name.startswith("."):
                continue
            path = Path(folder) / name
            if path.is_symlink() or not path.is_file():
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            bucket = direct.setdefault(key, [0, 0])
            bucket[0] += 1
            if name.endswith(".py"):
                bucket[1] += 1
                py_paths.append((path, size))
        if timed_out:
            break
    return direct, py_paths, timed_out


def python_files(repo):
    direct, py_paths, _timed_out = _collect(repo, float("inf"), time.perf_counter)
    del direct
    return [path for path, _size in py_paths]


def _fmt_dir(rel, files, py_count):
    return f"{rel} files={files} py={py_count}"


def _fit_summary(direct, max_chars):
    full = [_fmt_dir(rel, files, py_count) for rel, (files, py_count) in sorted(direct.items())]
    if len("\n".join(full)) <= max_chars:
        return full, False
    rolled = {}
    for rel, (files, py_count) in direct.items():
        top = "." if rel == "." else rel.split("/", 1)[0]
        bucket = rolled.setdefault(top, [0, 0])
        bucket[0] += files
        bucket[1] += py_count
    lines = [_fmt_dir(rel, files, py_count) for rel, (files, py_count) in sorted(rolled.items())]
    if len("\n".join(lines)) <= max_chars:
        return lines, True
    total_files = sum(files for files, _py_count in direct.values())
    total_py = sum(py_count for _files, py_count in direct.values())
    return [_fmt_dir(".", total_files, total_py)], True


def _header(files, shown_dirs, sigs, truncated):
    flag = 1 if truncated else 0
    return (
        f"map files={files} shown_dirs={shown_dirs} signatures={sigs} "
        f"truncated={flag} budget={CHAR_BUDGET}"
    )


def _sig_line(rel, names):
    visible = [name for name in names if not name.startswith("[")]
    if not visible:
        return None, 0
    return f"{rel}: " + ", ".join(visible), len(visible)


def _text_length(files, shown_dirs, note, dir_bytes, sig_count, sig_bytes):
    header = _header(files, shown_dirs, sig_count, bool(note))
    length = len(header) + 1
    if note:
        length += len("truncated: " + note) + 1
    length += len("summary:") + 1
    if dir_bytes:
        length += dir_bytes + 1
    length += len("signatures:")
    if sig_bytes:
        length += 1 + sig_bytes
    return length


def _compose(files, dir_lines, note, sig_lines, sig_count):
    header = _header(files, len(dir_lines), sig_count, bool(note))
    parts = [header]
    if note:
        parts.append("truncated: " + note)
    parts.append("summary:")
    parts.extend(dir_lines)
    parts.append("signatures:")
    parts.extend(sig_lines)
    text = "\n".join(parts)
    if len(text) > CHAR_BUDGET:
        text = text[:CHAR_BUDGET]
    return text


def _select_signatures(ordered, keywords, deadline, clock, room):
    """Return signature lines, name count, and whether some names were dropped."""
    if room <= 0:
        return [], 0, bool(ordered)
    chosen = []
    pending = []
    sig_count = 0
    sig_bytes = 0
    stopped = False
    seen = 0
    for path_overlap, depth, rel, path, size in ordered:
        if clock() >= deadline:
            stopped = True
            break
        seen += 1
        names = _read_signatures(path, size)
        line, count = _sig_line(rel, names)
        if line is None:
            continue
        if not keywords:
            extra = len(line) if sig_bytes == 0 else len(line) + 1
            if sig_bytes + extra > room:
                stopped = True
                break
            chosen.append(line)
            sig_bytes += extra
            sig_count += count
            continue
        sig_overlap = len(_sig_tokens(names) & keywords)
        pending.append((-(path_overlap + sig_overlap), depth, rel, line, count))
        if len(pending) >= PARSE_CAP:
            stopped = seen < len(ordered)
            break
    if not keywords:
        if seen < len(ordered):
            stopped = True
        return chosen, sig_count, stopped
    pending.sort()
    for _score, _depth, _rel, line, count in pending:
        extra = len(line) if sig_bytes == 0 else len(line) + 1
        if sig_bytes + extra > room:
            stopped = True
            break
        chosen.append(line)
        sig_bytes += extra
        sig_count += count
    if seen < len(ordered):
        stopped = True
    return chosen, sig_count, stopped


def render(repo, keywords=None, clock=None):
    clock = time.perf_counter if clock is None else clock
    repo = Path(repo)
    if not repo.is_dir():
        return _compose(0, [], "error", [], 0)
    started = clock()
    deadline = started + TIME_BUDGET
    keywords = _keywords_from(keywords)
    direct, py_paths, timed_out = _collect(repo, deadline, clock)
    total_files = sum(files for files, _py_count in direct.values())
    reserve = 360
    dir_lines, rolled = _fit_summary(direct, max(0, CHAR_BUDGET - reserve))
    dir_bytes = len("\n".join(dir_lines))
    if timed_out:
        note_for_room = NOTE_TIME
    elif rolled:
        note_for_room = NOTE_ROLL + "; " + NOTE_SIG
    else:
        note_for_room = NOTE_SIG
    room = CHAR_BUDGET - _text_length(total_files, len(dir_lines), note_for_room, dir_bytes, 0, 0)
    if room < 0:
        room = 0
    ordered = []
    for path, size in py_paths:
        rel = path.relative_to(repo).as_posix()
        overlap = len(_path_tokens(rel) & keywords) if keywords else 0
        ordered.append((overlap, rel.count("/"), rel, path, size))
    ordered.sort(key=lambda item: (-item[0], item[1], item[2]))
    sig_lines, sig_count, sig_dropped = _select_signatures(ordered, keywords, deadline, clock, room)
    if clock() >= deadline:
        timed_out = True
    if timed_out:
        note = NOTE_TIME
    else:
        parts = []
        if rolled:
            parts.append(NOTE_ROLL)
        if sig_dropped:
            parts.append(NOTE_SIG)
        note = "; ".join(parts)
    return _compose(total_files, dir_lines, note, sig_lines, sig_count)


def main(argv=None):
    list(sys.argv[1:] if argv is None else argv)
    try:
        print(render(root()))
    except Exception:
        print(
            f"map files=0 shown_dirs=0 signatures=0 truncated=1 budget={CHAR_BUDGET}\n"
            "truncated: error\n"
            "summary:\n"
            "signatures:"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
