"""Load the hygiene policy file. Patterns live in code; thresholds live here."""

import hashlib
from pathlib import Path

import yaml

from gemma_lab.hygiene.errors import HygieneInputError

DEFAULT_POLICY = Path("configs/hygiene/default.yaml")


def load_policy(path: Path | None = None) -> tuple[dict, str]:
    policy_path = Path(path) if path else DEFAULT_POLICY
    if not policy_path.is_file():
        raise HygieneInputError(f"Policy file not found: {policy_path}")
    raw = policy_path.read_bytes()
    loaded = yaml.safe_load(raw) or {}
    if not isinstance(loaded, dict):
        raise HygieneInputError("Hygiene policy must be a mapping")
    return loaded, hashlib.sha256(raw).hexdigest()
