"""GPU-only experimental SFT recipe; adapter compatibility requires harness evaluation.

Use a trainable, architecture-compatible Gemma 4 31B checkpoint. The competition's
compressed inference checkpoint is not assumed to be trainable by Transformers.
"""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path


def assistant_examples(tokenizer, messages, max_length):
    examples = []
    for index, message in enumerate(messages):
        if message.get("role") != "assistant":
            continue
        prompt = tokenizer.apply_chat_template(
            messages[:index], tokenize=True, add_generation_prompt=True
        )
        full = tokenizer.apply_chat_template(
            messages[: index + 1], tokenize=True, add_generation_prompt=False
        )
        # Never silently mask a mismatched template boundary or truncate away the answer.
        if full[: len(prompt)] != prompt:
            raise ValueError("Chat template prefix mismatch; inspect assistant masking")
        if len(full) > max_length or len(full) <= len(prompt):
            continue
        examples.append(
            {
                "input_ids": full,
                "attention_mask": [1] * len(full),
                "labels": [-100] * len(prompt) + full[len(prompt) :],
            }
        )
    return examples


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model-path", required=True, help="Trainable local Gemma 4 31B checkpoint"
    )
    parser.add_argument("--data", default="data/training/sft.jsonl")
    parser.add_argument("--output", default="runs/training/lora-v1")
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--max-length", type=int, default=4096)
    parser.add_argument("--epochs", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        Trainer,
        TrainingArguments,
        set_seed,
    )

    if not torch.cuda.is_available():
        raise RuntimeError("Dedicated NVIDIA GPU worker required")
    if not 1 <= args.rank <= 128:
        raise ValueError("LoRA rank must be 1..128")
    set_seed(args.seed)
    tokenizer = AutoTokenizer.from_pretrained(args.model_path, local_files_only=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    examples = []
    for line in Path(args.data).read_text().splitlines():
        examples.extend(
            assistant_examples(tokenizer, json.loads(line)["messages"], args.max_length)
        )
    if not examples:
        raise ValueError("No examples fit the context budget")
    model = AutoModelForCausalLM.from_pretrained(
        args.model_path, local_files_only=True, torch_dtype=torch.bfloat16
    )
    model.config.use_cache = False
    model = get_peft_model(
        model,
        LoraConfig(
            r=args.rank,
            lora_alpha=2 * args.rank,
            lora_dropout=0.05,
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
            task_type="CAUSAL_LM",
        ),
    )
    model.enable_input_require_grads()

    def collate(rows):
        length = max(len(r["input_ids"]) for r in rows)
        return {
            key: torch.tensor([r[key] + [pad] * (length - len(r[key])) for r in rows])
            for key, pad in [
                ("input_ids", tokenizer.pad_token_id),
                ("attention_mask", 0),
                ("labels", -100),
            ]
        }

    trainer = Trainer(
        model=model,
        train_dataset=examples,
        data_collator=collate,
        args=TrainingArguments(
            output_dir=args.output,
            per_device_train_batch_size=1,
            gradient_accumulation_steps=16,
            gradient_checkpointing=True,
            learning_rate=2e-4,
            num_train_epochs=args.epochs,
            bf16=True,
            logging_steps=5,
            save_strategy="epoch",
            report_to="none",
            seed=args.seed,
        ),
    )
    trainer.train()
    adapter = Path(args.output) / "adapter"
    model.save_pretrained(adapter, safe_serialization=True)
    manifest = {
        **vars(args),
        "training_examples": len(examples),
        "data_sha256": hashlib.sha256(Path(args.data).read_bytes()).hexdigest(),
        "packages": {
            name: importlib.metadata.version(name)
            for name in ["torch", "transformers", "peft", "accelerate"]
        },
        "inference_compatibility": "unverified; test with competition QAT model",
    }
    (Path(args.output) / "training_manifest.json").write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
