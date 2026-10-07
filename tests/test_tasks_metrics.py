import json

import pytest

from gemma_lab.metrics import compare, load_results, summary
from gemma_lab.tasks import export_tasks, split_tasks


def test_grouped_split_and_answer_redaction(tmp_path):
    tasks = [
        {
            "instance_id": f"task{i}",
            "repo": "org/repo",
            "base_commit": str(i // 2),
            "problem_statement": "Fix behavior",
            "patch": "SECRET ANSWER",
            "test_patch": "SECRET TEST",
            "FAIL_TO_PASS": ["secret_test"],
        }
        for i in range(50)
    ]
    source, split, exported = (
        tmp_path / "tasks.jsonl",
        tmp_path / "split.json",
        tmp_path / "safe.jsonl",
    )
    source.write_text("".join(json.dumps(t) + "\n" for t in tasks))
    result = split_tasks(source, split)
    assert result == split_tasks(source, split)
    groups = {}
    for partition, ids in result["partitions"].items():
        for task in tasks:
            if task["instance_id"] in ids:
                assert groups.setdefault(task["base_commit"], partition) == partition
    assert export_tasks(source, split, "train", exported) > 0
    assert "SECRET" not in exported.read_text()
    assert "FAIL_TO_PASS" not in exported.read_text()
    source.write_text(source.read_text() + "\n")
    with pytest.raises(ValueError, match="changed"):
        export_tasks(source, split, "train", exported)


def test_paired_comparison_detects_regressions():
    old = [{"instance_id": "a", "resolved": True}, {"instance_id": "b", "resolved": False}]
    new = [{"instance_id": "a", "resolved": False}, {"instance_id": "b", "resolved": True}]
    result = compare(old, new)
    assert result["wins"] == ["b"]
    assert result["regressions"] == ["a"]
    assert result["net_wins"] == 0
    with pytest.raises(ValueError, match="identical"):
        compare(old, new[:1])
    interval = summary(old)["wilson_95"]
    assert 0 <= interval[0] < 0.5 < interval[1] <= 1


def test_report_keeps_infrastructure_failures_visible():
    rows = [
        {"instance_id": "a", "resolved": False, "failure_class": "infrastructure_or_harness"},
        {"instance_id": "b", "resolved": False, "patch_chars": 0},
        {"instance_id": "c", "resolved": True, "patch_chars": 100},
    ]
    report = summary(rows)
    assert report["infrastructure_failures"] == 1
    assert report["empty_patches"] == 1
    assert report["tasks_with_patch_measurement"] == 2


def test_duplicate_results_rejected(tmp_path):
    path = tmp_path / "results.jsonl"
    row = {"instance_id": "same", "resolved": True}
    path.write_text((json.dumps(row) + "\n") * 2)
    with pytest.raises(ValueError, match="Duplicate"):
        load_results(path)
