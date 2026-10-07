"""Portable checks, deterministic archives, and provenance.

These checks supplement (and do not replace) the official swegemma validator.
"""

import json
import re
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import yaml

from gemma_lab.common import MODEL, git_revision, now, sha256, write_json

MAX_BYTES = 3 * 1024**3
# Conservative local policy. Official extension checks run in the GPU notebook too.
EXTENSIONS = {".yaml", ".yml", ".md", ".txt", ".json", ".safetensors", ".py"}
TOOLS = {
    "run_command",
    "submit_patch",
    "get_status",
    "read_file",
    "edit_file",
    "write_file",
    "get_code_neighbors",
    "search_similar_code",
    "get_code_subgraph",
    "agent_tool",
    "load_skill",
    "load_skill_resource",
    "run_skill_script",
}


def contained(root, path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError(f"Symlink is forbidden: {path}")
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes submission root: {path}")
    return resolved


def load_yaml(path, root, active=()):
    path = contained(root, path)
    if path in active:
        raise ValueError(f"Cyclic include: {path}")
    if len(active) > 10:
        raise ValueError("Include depth exceeds harness limit")
    if path.stat().st_size > 50 * 1024**2:
        raise ValueError("YAML file exceeds harness size limit")
    raw = path.read_text()
    if any(isinstance(event, yaml.AliasEvent) for event in yaml.parse(raw)):
        raise ValueError("YAML aliases are excluded by the portable validation policy")

    class Loader(yaml.SafeLoader):
        pass

    def include(loader, node):
        rel = loader.construct_scalar(node)
        if Path(rel).is_absolute() or ".." in Path(rel).parts:
            raise ValueError(f"Unsafe include: {rel}")
        target = contained(root, path.parent / rel)
        if target.suffix in {".yaml", ".yml"}:
            return load_yaml(target, root, (*active, path))
        return target.read_text()

    def mapping(loader, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in result:
                raise ValueError(f"Duplicate YAML key: {key}")
            result[key] = loader.construct_object(value_node, deep=deep)
        return result

    Loader.add_constructor("!include", include)
    Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    return yaml.load(raw, Loader=Loader)


def validate(source: Path):
    source = source.resolve()
    if not (source / "agent.yaml").is_file():
        raise ValueError("agent.yaml must exist at the submission root")
    roots = [
        source / name for name in ("agent.yaml", "agent.yml", "root_agent.yaml", "root_agent.yml")
    ]
    if sum(path.exists() for path in roots) != 1:
        raise ValueError("Exactly one root agent config is required")
    files = []
    for path in sorted(source.rglob("*")):
        contained(source, path)
        if path.is_file():
            if path.suffix.lower() not in EXTENSIONS or any(
                part.startswith(".") for part in path.relative_to(source).parts
            ):
                raise ValueError(f"Unsupported/hidden submission file: {path}")
            if path.name in {"kaggle.json", "credentials.json", "access_token"}:
                raise ValueError(f"Credential file forbidden: {path.name}")
            files.append(path)
    if len(files) > 10_000:
        raise ValueError("Submission exceeds 10,000 files")
    if sum(p.stat().st_size for p in files) >= MAX_BYTES:
        raise ValueError("Submission exceeds 3 GiB uncompressed")
    root_config = load_yaml(source / "agent.yaml", source)
    if not isinstance(root_config, dict) or not root_config.get("name"):
        raise ValueError("Root agent must be a mapping with a name")
    models = []

    def visit(value):
        if isinstance(value, dict):
            if "model" in value:
                models.append(value["model"])
                if value["model"] != MODEL:
                    raise ValueError(f"Every agent must use {MODEL}")
            if "agent_class" in value and value["agent_class"] not in {
                "LlmAgent",
                "SequentialAgent",
                "ParallelAgent",
                "LoopAgent",
            }:
                raise ValueError("Unsupported agent class")
            for skill in value.get("skills", []):
                if Path(skill).is_absolute() or ".." in Path(skill).parts:
                    raise ValueError("Unsafe skill path")
                if not contained(source, source / skill / "SKILL.md").is_file():
                    raise ValueError(f"Missing skill manifest: {skill}")
            if "adapter" in value:
                adapter_name = value["adapter"]
                if not isinstance(adapter_name, str) or not re.fullmatch(r"[\w-]+", adapter_name):
                    raise ValueError("Adapter must be a simple directory name")
                adapter = source / "adapters" / adapter_name
                for name in ["adapter_config.json", "adapter_model.safetensors"]:
                    if not contained(source, adapter / name).is_file():
                        raise ValueError(f"Missing adapter file: {adapter / name}")
                cfg = json.loads((adapter / "adapter_config.json").read_text())
                if cfg.get("r", 0) > 128:
                    raise ValueError("Starter vLLM runtime supports LoRA rank <= 128")
            for tool in value.get("tools", []):
                name = (
                    ("agent_tool" if "agent_tool" in tool else tool.get("name"))
                    if isinstance(tool, dict)
                    else tool
                )
                if name not in TOOLS:
                    raise ValueError(f"Unsupported harness tool: {name}")
            sampling = value.get("generate_content_config", {})
            allowed = {
                "temperature",
                "top_p",
                "top_k",
                "max_output_tokens",
                "presence_penalty",
                "frequency_penalty",
                "stop_sequences",
                "response_mime_type",
                "seed",
                "thinking_config",
            }
            if set(sampling) - allowed:
                raise ValueError("Unsupported generation config fields")
            if not 1 <= sampling.get("max_output_tokens", 16384) <= 32768:
                raise ValueError("max_output_tokens outside harness limits")
            if not 0 <= sampling.get("thinking_config", {}).get("thinking_budget", 4096) <= 32768:
                raise ValueError("thinking_budget outside harness limits")
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    # Parse every YAML: includes, subagent files, and config_path references.
    for path in files:
        if path.suffix in {".yaml", ".yml"}:
            value = load_yaml(path, source)
            visit(value)
            check_references(value, path.parent, source)
    if not models:
        raise ValueError("No explicitly declared competition model")
    for manifest in source.glob("skills/*/SKILL.md"):
        parts = manifest.read_text().split("---", 2)
        if len(parts) < 3 or not yaml.safe_load(parts[1]).get("name"):
            raise ValueError(f"Skill needs YAML frontmatter with name: {manifest}")
    return files


def check_references(value, parent, root):
    if isinstance(value, dict):
        if "config_path" in value:
            target = value["config_path"]
            if Path(target).is_absolute() or ".." in Path(target).parts:
                raise ValueError(f"Unsafe config_path: {target}")
            if not contained(root, parent / target).is_file():
                raise ValueError(f"Missing config_path: {target}")
        for child in value.values():
            check_references(child, parent, root)
    elif isinstance(value, list):
        for child in value:
            check_references(child, parent, root)


def pack(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    files = validate(source)
    if output.is_relative_to(source):
        raise ValueError("Archive output must be outside the agent directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(source).as_posix(), (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            with path.open("rb") as src, archive.open(info, "w") as dst:
                import shutil

                shutil.copyfileobj(src, dst)
    manifest = {
        "created_at": now(),
        "git_revision": git_revision(),
        "sha256": sha256(output),
        "source": str(source),
        "archive": str(output),
        "files": {p.relative_to(source).as_posix(): sha256(p) for p in files},
        "validation": "portable checks only; official GPU harness required",
    }
    write_json(output.with_suffix(".manifest.json"), manifest)
    return manifest


def validate_archive(path):
    with tempfile.TemporaryDirectory() as folder, zipfile.ZipFile(path) as archive:
        names = set()
        total = 0
        for item in archive.infolist():
            rel = PurePosixPath(item.filename)
            if rel.is_absolute() or ".." in rel.parts or "\\" in item.filename:
                raise ValueError(f"Unsafe archive entry: {item.filename}")
            if item.filename in names:
                raise ValueError(f"Duplicate archive entry: {item.filename}")
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Archive symlinks forbidden")
            names.add(item.filename)
            total += item.file_size
        if total > MAX_BYTES:
            raise ValueError("Archive exceeds uncompressed size limit")
        archive.extractall(folder)
        validate(Path(folder))
