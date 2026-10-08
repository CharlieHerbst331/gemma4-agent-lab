import hashlib

import pytest

from gemma_lab.common import MODEL
from gemma_lab.paired import (
    PinError,
    assert_arms_compatible,
    build_schedule,
    import_origin_risk,
    inspect_arm,
    install_arm,
    make_pair_id,
    schedule_sha256,
    src_layout_from_names,
    verify_extracted_tree,
)


def test_schedule_counterbalances_odd_and_even_cohorts():
    for size in (13, 14):
        ids = [f"t{index:02d}" for index in range(size)]
        schedule = build_schedule(ids, repeats=2)
        repeat1 = [entry for entry in schedule["entries"] if entry["repeat"] == 1]
        assert [entry["task_id"] for entry in repeat1] == ids
        assert [entry["order"][0] for entry in repeat1] == [
            "A" if index % 2 == 0 else "B" for index in range(size)
        ]
        repeat2 = [entry for entry in schedule["entries"] if entry["repeat"] == 2]
        assert [entry["task_id"] for entry in repeat2] == list(reversed(ids))
        first = {}
        for entry in schedule["entries"]:
            first.setdefault(entry["task_id"], []).append(entry["order"][0])
        assert all(len(set(arms)) == 2 for arms in first.values())


def test_naive_position_rule_fails_for_thirteen_tasks():
    ids = [f"t{index:02d}" for index in range(13)]
    naive = {}
    for repeat, order in ((0, ids), (1, list(reversed(ids)))):
        naive[repeat] = {
            task_id: "A" if position % 2 == 0 else "B" for position, task_id in enumerate(order)
        }
    assert naive[0] == naive[1]
    ours = build_schedule(ids, repeats=2)
    by_task = {}
    for entry in ours["entries"]:
        by_task.setdefault(entry["task_id"], []).append(entry["order"][0])
    assert all(arms[0] != arms[1] for arms in by_task.values())


def test_schedule_hash_and_shuffle_are_deterministic():
    ids = ["c", "a", "b"]
    first = build_schedule(ids, repeats=2, shuffle_seed=3)
    second = build_schedule(ids, repeats=2, shuffle_seed=3)
    other = build_schedule(ids, repeats=2, shuffle_seed=4)
    assert first["sha256"] == second["sha256"] == schedule_sha256(first["entries"])
    assert first["task_ids"] == second["task_ids"]
    assert first["task_ids"] != other["task_ids"]
    entry = first["entries"][0]
    assert entry["pair_id"] == make_pair_id(first["sha256"], entry["repeat"], entry["task_id"])


def test_payload_is_hashed_before_extraction(tmp_path):
    dest = tmp_path / "arm"
    with pytest.raises(PinError, match="before extraction"):
        install_arm(b"not-a-zip", "0" * 64, dest, {})
    assert not dest.exists()


def test_extracted_tree_refuses_extra_missing_and_changed_files(tmp_path):
    payload_root = tmp_path / "src"
    payload_root.mkdir()
    (payload_root / "agent.yaml").write_text("name: one\n")
    import zipfile

    blob = tmp_path / "arm.zip"
    with zipfile.ZipFile(blob, "w") as archive:
        archive.write(payload_root / "agent.yaml", "agent.yaml")
    payload = blob.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    files = {"agent.yaml": hashlib.sha256(b"name: one\n").hexdigest()}
    dest = tmp_path / "out"
    install_arm(payload, digest, dest, files)
    (dest / "extra.txt").write_text("x")
    with pytest.raises(PinError, match="extra"):
        verify_extracted_tree(dest, files)
    (dest / "extra.txt").unlink()
    (dest / "agent.yaml").write_text("changed\n")
    with pytest.raises(PinError, match="changed"):
        verify_extracted_tree(dest, files)
    (dest / "agent.yaml").unlink()
    with pytest.raises(PinError, match="missing"):
        verify_extracted_tree(dest, files)


def _arm(tmp_path, name, *, thinking_path, thinking_budget=0, model=MODEL, minutes=4.5):
    root = tmp_path / name
    root.mkdir(parents=True)
    thinking = root / thinking_path
    thinking.parent.mkdir(parents=True, exist_ok=True)
    thinking.write_text(f"thinking_budget: {thinking_budget}\ninclude_thoughts: true\n")
    include = thinking_path
    if name == "single":
        (root / "agent.yaml").write_text(
            "agent_class: LlmAgent\n"
            f"name: {name}\n"
            f"model: {model}\n"
            "instruction: !include prompts/system.md\n"
            "generate_content_config:\n"
            "  temperature: 0.5\n"
            "  top_p: 0.95\n"
            f"  thinking_config: !include {include}\n"
        )
    else:
        (root / "agent.yaml").write_text(
            "agent_class: SequentialAgent\n"
            f"name: {name}\n"
            "sub_agents:\n"
            "- config_path: sub_agents/role.yaml\n"
            "- config_path: sub_agents/other.yaml\n"
        )
        role = (
            "agent_class: LlmAgent\n"
            "name: role\n"
            f"model: {model}\n"
            "instruction: !include role.md\n"
            "generate_content_config:\n"
            "  temperature: 0.5\n"
            "  top_p: 0.95\n"
            "  thinking_config: !include thinking.yaml\n"
        )
        (root / "sub_agents" / "role.yaml").write_text(role)
        (root / "sub_agents" / "other.yaml").write_text(role.replace("name: role", "name: other"))
        (root / "sub_agents" / "role.md").write_text("role\n")
    (root / "prompts").mkdir(exist_ok=True)
    (root / "prompts" / "system.md").write_text(f"prompt {name}\n")
    (root / "eval_config.yaml").write_text(
        "evaluation:\n"
        "  timeout_seconds: 300\n"
        "  max_tool_calls: 48\n"
        f"  max_time_minutes: {minutes}\n"
        "  max_turns: 48\n"
    )
    return root


def test_resolved_thinking_settings_ignore_include_path(tmp_path):
    single = _arm(tmp_path, "single", thinking_path="thinking.yaml")
    multi = _arm(tmp_path, "multi", thinking_path="sub_agents/thinking.yaml")
    left = inspect_arm(single)
    right = inspect_arm(multi)
    assert left["sampling"] == right["sampling"]
    assert left["sampling"] == [(0.5, 0.95, 0, True)]
    assert left["budgets"] == right["budgets"]
    assert_arms_compatible(
        left,
        right,
        allow_identical=False,
        allowed_differences=["agent.yaml", "sub_agents/*", "prompts/*"],
        sha_a="a" * 64,
        sha_b="b" * 64,
    )
    changed = _arm(
        tmp_path / "again",
        "multi",
        thinking_path="sub_agents/thinking.yaml",
        thinking_budget=256,
    )
    with pytest.raises(ValueError, match="Resolved generation settings"):
        assert_arms_compatible(
            left,
            inspect_arm(changed),
            allow_identical=False,
            allowed_differences=["agent.yaml", "sub_agents/*", "prompts/*"],
            sha_a="a" * 64,
            sha_b="c" * 64,
        )


def test_identical_budget_model_and_adapter_refusals(tmp_path):
    left = inspect_arm(_arm(tmp_path, "single", thinking_path="thinking.yaml"))
    with pytest.raises(ValueError, match="identical"):
        assert_arms_compatible(
            left,
            left,
            allow_identical=False,
            allowed_differences=["prompts/*"],
            sha_a="a" * 64,
            sha_b="a" * 64,
        )
    other_model = inspect_arm(
        _arm(tmp_path / "model", "single", thinking_path="thinking.yaml", model="other-model")
    )
    with pytest.raises(ValueError, match="model"):
        assert_arms_compatible(
            left,
            other_model,
            allow_identical=False,
            allowed_differences=["agent.yaml", "prompts/*"],
            sha_a="a" * 64,
            sha_b="b" * 64,
        )
    other_budget = inspect_arm(
        _arm(tmp_path / "budget", "single", thinking_path="thinking.yaml", minutes=6.0)
    )
    with pytest.raises(ValueError, match="budgets"):
        assert_arms_compatible(
            left,
            other_budget,
            allow_identical=False,
            allowed_differences=["agent.yaml", "prompts/*", "eval_config.yaml"],
            sha_a="a" * 64,
            sha_b="b" * 64,
        )
    adapter = tmp_path / "single"
    (adapter / "adapters").mkdir()
    (adapter / "adapters" / "lora.safetensors").write_bytes(b"x")
    with pytest.raises(ValueError, match="LoRA"):
        assert_arms_compatible(
            inspect_arm(adapter),
            left,
            allow_identical=False,
            allowed_differences=["prompts/*", "adapters/*"],
            sha_a="a" * 64,
            sha_b="b" * 64,
        )


def test_import_origin_listing_wins_on_disagreement(tmp_path):
    flagged, packages = src_layout_from_names(["src/requests/__init__.py", "README.md"])
    assert flagged and packages == ["requests"]
    assert src_layout_from_names(["fastapi/__init__.py"]) == (False, [])
    record = import_origin_risk("psf/requests", ["psf/requests"], ["requests/__init__.py"])
    assert record["repo_list_src_layout"] is True
    assert record["snapshot_src_layout"] is False
    assert record["disagreement"] is True
    assert record["src_layout"] is False
    archive = tmp_path / "snap.tar"
    import tarfile

    with tarfile.open(archive, "w") as handle:
        info = tarfile.TarInfo("src/requests/__init__.py")
        handle.addfile(info)
    from gemma_lab.paired import list_tar_members

    listed = import_origin_risk("psf/requests", ["psf/requests"], list_tar_members(archive))
    assert listed["src_layout"] is True
    assert listed["grading_origin"] == "host-likely"
