"""One-string locate. The only call passes a single literal in args.

The subprocess sandbox rewrites /tmp and /workspace only inside command
strings. This script finds the repo from GEMMA_CHECK_ROOT, then /workspace,
then PYTHONPATH. It prints each hit with a few surrounding lines and stops.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SKIP = {".git", ".venv", "node_modules", "__pycache__"}
MAX_HITS = 5
MAX_FILES = 800
MAX_CHARS = 1500
WINDOW = 2
LINE_CHARS = 160
CALL = '{"skill_name":"locate","file_path":"scripts/run.py","args":["literal text"]}'


def root():
    candidates = [os.environ.get("GEMMA_CHECK_ROOT"), "/workspace"]
    candidates.extend(os.environ.get("PYTHONPATH", "").split(os.pathsep))
    for cand in candidates:
        if cand and (Path(cand) / ".git").exists():
            return Path(cand)
    return Path("/workspace")


def cap(text, limit=MAX_CHARS):
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n[truncated]"


def _window(lines, index):
    start = max(0, index - WINDOW)
    end = min(len(lines), index + WINDOW + 1)
    shown = []
    for number in range(start, end):
        text = lines[number][:LINE_CHARS]
        shown.append(f"{number + 1}|{text}")
    return shown


def search(repo, needle):
    hits = []
    scanned = 0
    stopped = False
    for folder, directories, filenames in os.walk(repo, followlinks=False):
        directories[:] = sorted(
            name
            for name in directories
            if name not in SKIP
            and not name.startswith(".")
            and not (Path(folder) / name).is_symlink()
        )
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            path = Path(folder) / name
            if path.is_symlink() or not path.is_file():
                continue
            scanned += 1
            if scanned > MAX_FILES:
                stopped = True
                break
            try:
                if path.stat().st_size > 512 * 1024:
                    continue
                lines = path.read_text(errors="replace").splitlines()
            except OSError:
                continue
            relative = path.relative_to(repo).as_posix()
            for index, line in enumerate(lines):
                if needle not in line:
                    continue
                hits.append((relative, index, lines))
                if len(hits) > MAX_HITS:
                    stopped = True
                    break
            if stopped:
                break
        if stopped:
            break
    return hits[:MAX_HITS], stopped


def render(needle, hits, stopped):
    lines = [f"locate: {len(hits)} hit(s) for {needle!r}"]
    for relative, index, content in hits:
        lines.append(f"{relative}:{index + 1}")
        lines.extend(_window(content, index))
    if stopped:
        lines.append("more hits omitted")
    return cap("\n".join(lines))


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or not args[0].strip():
        print("locate needs one literal string: " + CALL)
        return 0
    needle = args[0]
    hits, stopped = search(root(), needle)
    print(render(needle, hits, stopped))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
