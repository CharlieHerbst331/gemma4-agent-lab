"""Select verified, normalized chat trajectories from the frozen training split.

Input JSONL schema: instance_id, resolved (bool), messages (native chat/tool messages).
Normalize official ATIF traces explicitly before this step; preserve tool-call IDs.
"""

import argparse
import hashlib
import json
from pathlib import Path


def prepare(trajectories, splits, output):
    manifest = json.loads(Path(splits).read_text())
    train_ids = set(manifest["partitions"]["train"])
    selected, seen = [], set()
    for line in Path(trajectories).read_text().splitlines():
        row = json.loads(line)
        if row["instance_id"] not in train_ids or row.get("resolved") is not True:
            continue
        messages = row["messages"]
        if not messages or not any(m.get("role") == "assistant" for m in messages):
            raise ValueError("Trajectory must contain assistant messages")
        digest = hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        selected.append({"instance_id": row["instance_id"], "messages": messages})
    if not selected:
        raise ValueError("No verified training trajectories; refusing empty training data")
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text("".join(json.dumps(r) + "\n" for r in selected))
    return len(selected)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("trajectories")
    parser.add_argument("--splits", default="configs/splits/public-v1.json")
    parser.add_argument("--output", default="data/training/sft.jsonl")
    args = parser.parse_args()
    print(f"Selected {prepare(args.trajectories, args.splits, args.output)} trajectories")
