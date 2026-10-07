import shutil
import zipfile
from pathlib import Path

import pytest

from gemma_lab.bundle import pack, validate, validate_archive
from gemma_lab.common import MODEL


@pytest.fixture
def agent(tmp_path):
    folder = tmp_path / "agent"
    shutil.copytree(Path("agents/baseline"), folder)
    return folder


def test_reproducible_root_archive(agent, tmp_path):
    left, right = tmp_path / "a.zip", tmp_path / "b.zip"
    assert pack(agent, left)["sha256"] == pack(agent, right)["sha256"]
    with zipfile.ZipFile(left) as archive:
        assert "agent.yaml" in archive.namelist()
    validate_archive(left)


def test_wrong_model_in_subagent_rejected(agent):
    (agent / "sub.yaml").write_text("name: helper\nmodel: some-other-model\n")
    with pytest.raises(ValueError, match="Every agent"):
        validate(agent)


@pytest.mark.parametrize("ref", ["../secret.md", "/etc/passwd"])
def test_include_escape(agent, ref):
    (agent / "agent.yaml").write_text(f"name: a\nmodel: {MODEL}\ninstruction: !include {ref}\n")
    with pytest.raises(ValueError, match="Unsafe include"):
        validate(agent)


def test_symlink_rejected(agent, tmp_path):
    (tmp_path / "secret.md").write_text("secret")
    (agent / "leak.md").symlink_to(tmp_path / "secret.md")
    with pytest.raises(ValueError, match="Symlink"):
        validate(agent)


def test_cyclic_include(agent):
    (agent / "a.yaml").write_text("value: !include b.yaml\n")
    (agent / "b.yaml").write_text("value: !include a.yaml\n")
    with pytest.raises(ValueError, match="Cyclic"):
        validate(agent)


def test_duplicate_yaml_key(agent):
    (agent / "agent.yaml").write_text(f"name: a\nmodel: {MODEL}\nmodel: bad\n")
    with pytest.raises(ValueError, match="Duplicate YAML"):
        validate(agent)


@pytest.mark.parametrize("filename", ["kaggle.json", ".env", "bad.bin", "run.sh"])
def test_forbidden_payloads(agent, filename):
    (agent / filename).write_text("do not publish")
    with pytest.raises(ValueError):
        validate(agent)


def test_zip_slip(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../escape.txt", "bad")
    with pytest.raises(ValueError, match="Unsafe archive"):
        validate_archive(archive)


def test_missing_adapter(agent):
    with (agent / "agent.yaml").open("a") as handle:
        handle.write("adapter: missing\n")
    with pytest.raises(ValueError, match="Missing adapter"):
        validate(agent)


def test_multiple_roots(agent):
    shutil.copyfile(agent / "agent.yaml", agent / "root_agent.yaml")
    with pytest.raises(ValueError, match="Exactly one"):
        validate(agent)


def test_generation_ceiling(agent):
    (agent / "configs/sampling.yaml").write_text("max_output_tokens: 32769\n")
    with pytest.raises(ValueError, match="max_output_tokens"):
        validate(agent)


def test_alias_cycle_rejected(agent):
    (agent / "loop.yaml").write_text("loop: &loop\n  self: *loop\n")
    with pytest.raises(ValueError, match="aliases"):
        validate(agent)
