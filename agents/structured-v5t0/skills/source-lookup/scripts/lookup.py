"""Read-only literal lookup/source windows with explicit limits and provenance."""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

SKIP = {".git", ".venv", "node_modules", "__pycache__"}
EXTENSIONS = {".py", ".toml", ".cfg", ".yaml", ".yml", ".js", ".ts", ".md"}


def inside(root, value):
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Use workspace-relative paths without traversal")
    path = root / relative
    if any(p.is_symlink() for p in [path, *path.parents] if p.is_relative_to(root)):
        raise ValueError("Symlink paths are not searched")
    if not path.resolve().is_relative_to(root):
        raise ValueError("Path escapes workspace")
    if any(p in SKIP or p.startswith(".") for p in relative.parts):
        raise ValueError("Excluded directory/file")
    return path


def source_files(base, root, deadline):
    if base.is_file():
        yield base
        return
    for folder, directories, filenames in os.walk(base, followlinks=False):
        if time.monotonic() >= deadline:
            return
        directories[:] = sorted(
            d
            for d in directories
            if d not in SKIP
            and not d.startswith(".")
            and not (Path(folder) / d).is_symlink()
            and not (Path(folder) == root and d in {"data", "vendor", "benchmarks"})
        )
        for name in sorted(filenames):
            yield Path(folder) / name


def lookup(workspace, query=None, scopes=None, filepath=None, start=1, end=60):
    root = Path(workspace).resolve()
    if not (root / ".git").exists():
        raise ValueError("Require a Git workspace")
    if filepath:
        path = inside(root, filepath)
        if not 1 <= start <= end or end - start >= 80:
            raise ValueError("Use integer 1-based ranges of at most 80 lines")
        if path.stat().st_size > 1024 * 1024:
            raise ValueError("File exceeds 1 MiB window limit")
        lines = path.read_text(errors="replace").splitlines()
        if start > len(lines):
            raise ValueError("Start line exceeds file length")
        result = {
            "kind": "window",
            "filepath": filepath,
            "start_line": start,
            "end_line": min(end, len(lines)),
            "total_lines": len(lines),
            "content": "\n".join(
                f"{i + 1}: {lines[i][:300]}" for i in range(start - 1, min(end, len(lines)))
            ),
        }
    else:
        if (
            not isinstance(query, list)
            or not 1 <= len(query) <= 4
            or any(not isinstance(q, str) or not q or len(q) > 120 for q in query)
        ):
            raise ValueError("query must contain 1-4 short literal strings")
        scopes = scopes or ["."]
        if (
            not isinstance(scopes, list)
            or not 1 <= len(scopes) <= 4
            or any(not isinstance(x, str) or not x or len(x) > 200 for x in scopes)
        ):
            raise ValueError("Use 1-4 scope paths")
        hits, scanned, bounded, seen = [], 0, False, set()
        deadline = time.monotonic() + 5
        for scope in scopes:
            base = inside(root, scope)
            candidates = source_files(base, root, deadline)
            for path in candidates:
                if time.monotonic() >= deadline or scanned >= 1200 or len(hits) >= 20:
                    bounded = True
                    break
                rel = path.relative_to(root)
                if (
                    any(p in SKIP or p.startswith(".") for p in rel.parts)
                    or path.suffix not in EXTENSIONS
                    or path in seen
                ):
                    continue
                seen.add(path)
                try:
                    path = inside(root, str(rel))
                    if not path.is_file() or path.stat().st_size > 512 * 1024:
                        continue
                    scanned += 1
                    for line, text in enumerate(path.read_text(errors="replace").splitlines(), 1):
                        matched = [q for q in query if q in text]
                        if matched:
                            hits.append(
                                {
                                    "path": str(rel),
                                    "line": line,
                                    "matched": matched,
                                    "text": text[:160],
                                }
                            )
                            if len(hits) >= 20:
                                bounded = True
                                break
                except (OSError, ValueError):
                    continue
            if time.monotonic() >= deadline:
                bounded = True
            if bounded:
                break
        result = {
            "kind": "literal-search",
            "query": query,
            "scopes": scopes,
            "files_scanned": scanned,
            "hits": hits,
            "bounded": bounded,
        }
    result["query_key"] = hashlib.sha256(
        json.dumps([query, scopes, filepath, start, end], sort_keys=True).encode()
    ).hexdigest()[:16]
    if result["kind"] == "window":
        while len(json.dumps(result, ensure_ascii=True)) > 4000 and result["content"]:
            result["content"] = (
                result["content"].rsplit("\n", 1)[0] if "\n" in result["content"] else ""
            )
            result["truncated"] = True
        result["end_line"] = start + len(result["content"].splitlines()) - 1
    else:
        while len(json.dumps(result, ensure_ascii=True)) > 4000 and result["hits"]:
            result["hits"].pop()
            result["bounded"] = True
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=os.environ.get("PWD", "/workspace"))
    parser.add_argument("--query", default="[]")
    parser.add_argument("--term", action="append")
    parser.add_argument("--scope", action="append")
    parser.add_argument("--scopes", default='["."]')
    parser.add_argument("--file")
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=60)
    args = parser.parse_args()
    try:
        result = lookup(
            args.workspace,
            args.term or json.loads(args.query),
            args.scope or json.loads(args.scopes),
            args.file,
            args.start,
            args.end,
        )
        print(json.dumps({"ok": True, **result}, ensure_ascii=True))
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:500]}))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
