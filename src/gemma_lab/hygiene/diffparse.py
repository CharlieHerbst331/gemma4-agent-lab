"""Parse unified diffs produced by git or written as synthetic fixtures."""

import re
from dataclasses import dataclass, field


@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str] = field(default_factory=list)


@dataclass
class FileDiff:
    old_path: str | None
    new_path: str | None
    added: bool = False
    deleted: bool = False
    renamed: bool = False
    binary: bool = False
    old_mode: str | None = None
    new_mode: str | None = None
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def path(self) -> str:
        return self.new_path or self.old_path or ""

    def added_lines(self) -> list[tuple[int, str]]:
        found = []
        for hunk in self.hunks:
            line_no = hunk.new_start
            for raw in hunk.lines:
                if raw.startswith("\\"):
                    continue
                if raw.startswith("+"):
                    found.append((line_no, raw[1:]))
                    line_no += 1
                elif raw.startswith("-"):
                    continue
                else:
                    line_no += 1
        return found


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse_diff(text: str) -> list[FileDiff]:
    if not text or not text.strip():
        return []
    lines = text.splitlines()
    starts = [index for index, line in enumerate(lines) if line.startswith("diff --git ")]
    if not starts:
        return [_parse_plain(lines)]
    files = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(lines)
        files.append(_parse_git_section(lines[start:end]))
    return files


def _parse_git_section(lines: list[str]) -> FileDiff:
    old_raw, new_raw = _header_paths(lines[0])
    parsed = FileDiff(old_path=_strip_ab(old_raw), new_path=_strip_ab(new_raw))
    index = 1
    while index < len(lines):
        line = lines[index]
        if line.startswith("@@"):
            hunk, index = _parse_hunk(lines, index)
            parsed.hunks.append(hunk)
            continue
        if line.startswith("new file mode "):
            parsed.added = True
            parsed.new_mode = line.split()[-1]
        elif line.startswith("deleted file mode "):
            parsed.deleted = True
            parsed.old_mode = line.split()[-1]
        elif line.startswith("old mode "):
            parsed.old_mode = line.split()[-1]
        elif line.startswith("new mode "):
            parsed.new_mode = line.split()[-1]
        elif line.startswith("rename from "):
            parsed.renamed = True
            parsed.old_path = line[len("rename from ") :]
        elif line.startswith("rename to "):
            parsed.renamed = True
            parsed.new_path = line[len("rename to ") :]
        elif line.startswith("copy from "):
            parsed.old_path = line[len("copy from ") :]
        elif line.startswith("copy to "):
            parsed.added = True
            parsed.new_path = line[len("copy to ") :]
        elif line.startswith("Binary files ") or line.startswith("GIT binary patch"):
            parsed.binary = True
            break
        elif line.startswith("--- "):
            _apply_minus(parsed, line[4:].split("\t", 1)[0].strip())
        elif line.startswith("+++ "):
            _apply_plus(parsed, line[4:].split("\t", 1)[0].strip())
        index += 1
    return parsed


def _parse_plain(lines: list[str]) -> FileDiff:
    parsed = FileDiff(old_path=None, new_path=None)
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("--- "):
            _apply_minus(parsed, line[4:].split("\t", 1)[0].strip())
        elif line.startswith("+++ "):
            _apply_plus(parsed, line[4:].split("\t", 1)[0].strip())
        elif line.startswith("@@"):
            hunk, index = _parse_hunk(lines, index)
            parsed.hunks.append(hunk)
            continue
        elif line.startswith("Binary files "):
            parsed.binary = True
        index += 1
    return parsed


def _parse_hunk(lines: list[str], index: int) -> tuple[Hunk, int]:
    match = _HUNK.match(lines[index])
    if not match:
        raise ValueError(f"Malformed hunk header: {lines[index]}")
    old_start, old_count, new_start, new_count = match.groups()
    hunk = Hunk(int(old_start), int(old_count or 1), int(new_start), int(new_count or 1))
    index += 1
    while index < len(lines):
        line = lines[index]
        if line.startswith(("diff --git ", "@@")):
            break
        if line.startswith((" ", "+", "-", "\\")) or line == "":
            hunk.lines.append(line if line else " ")
            index += 1
            continue
        break
    return hunk, index


def _apply_minus(parsed: FileDiff, path: str) -> None:
    if path == "/dev/null":
        parsed.added = True
        parsed.old_path = None
        return
    parsed.old_path = _strip_ab(path)


def _apply_plus(parsed: FileDiff, path: str) -> None:
    if path == "/dev/null":
        parsed.deleted = True
        parsed.new_path = None
        return
    parsed.new_path = _strip_ab(path)


def _header_paths(header: str) -> tuple[str, str]:
    spec = header[len("diff --git ") :]
    if spec.startswith('"'):
        tokens = _git_tokens(spec)
        if len(tokens) != 2:
            raise ValueError(f"Unrecognized diff header: {header}")
        return tokens[0], tokens[1]
    # Git leaves spaces unquoted. The two paths are separated by " b/".
    pivot = spec.find(" b/")
    if pivot <= 0 or not spec.startswith("a/"):
        raise ValueError(f"Unrecognized diff header: {header}")
    return spec[:pivot], spec[pivot + 1 :]


def _git_tokens(spec: str) -> list[str]:
    tokens = []
    index = 0
    while index < len(spec):
        if spec[index].isspace():
            index += 1
            continue
        if spec[index] == '"':
            index += 1
            chars = []
            while index < len(spec) and spec[index] != '"':
                if spec[index] == "\\" and index + 1 < len(spec):
                    chars.append(spec[index + 1])
                    index += 2
                    continue
                chars.append(spec[index])
                index += 1
            tokens.append("".join(chars))
            index += 1
            continue
        end = index
        while end < len(spec) and not spec[end].isspace():
            end += 1
        tokens.append(spec[index:end])
        index = end
    return tokens


def _strip_ab(path: str) -> str | None:
    if path == "/dev/null":
        return None
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path
