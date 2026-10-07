import importlib.util
import json
from pathlib import Path


def module(name):
    spec = importlib.util.spec_from_file_location(name, Path("training") / f"{name}.py")
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_training_filter_excludes_holdout_and_failed_tasks(tmp_path):
    source, splits, output = (
        tmp_path / "traces.jsonl",
        tmp_path / "split.json",
        tmp_path / "sft.jsonl",
    )
    rows = [
        {
            "instance_id": i,
            "resolved": resolved,
            "messages": [{"role": "user", "content": i}, {"role": "assistant", "content": "fix"}],
        }
        for i, resolved in [("train1", True), ("train2", False), ("holdout", True)]
    ]
    source.write_text("".join(json.dumps(r) + "\n" for r in rows))
    splits.write_text(json.dumps({"partitions": {"train": ["train1", "train2"]}}))
    assert module("prepare_data").prepare(source, splits, output) == 1
    assert json.loads(output.read_text())["instance_id"] == "train1"


def test_sft_masks_prompt_and_drops_overlong_answer():
    class Tokenizer:
        def apply_chat_template(self, messages, tokenize, add_generation_prompt):
            return list(range(len(messages) * 3 + (1 if add_generation_prompt else 0)))

    messages = [{"role": "user"}, {"role": "assistant"}]
    recipe = module("train_lora")
    sample = recipe.assistant_examples(Tokenizer(), messages, 10)[0]
    assert sample["labels"] == [-100, -100, -100, -100, 4, 5]
    assert recipe.assistant_examples(Tokenizer(), messages, 5) == []
