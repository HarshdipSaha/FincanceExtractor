from __future__ import annotations

import os
import re
from pathlib import Path


def load_local_keys(base_dir: Path) -> None:
    """Load the simple local `keys` file without printing secrets."""
    keys_path = base_dir / "keys"
    if not keys_path.exists():
        return
    text = keys_path.read_text(encoding="utf-8", errors="ignore")
    patterns = {
        "GROQ_API_KEY": r"groq\s*key\s*=\s*([^\s]+)",
        "LLAMA_CLOUD_API_KEY": r"llama\s*cloud\s*api\s*key\s*=\s*([^\s]+)",
    }
    for env_name, pattern in patterns.items():
        if os.environ.get(env_name):
            continue
        match = re.search(pattern, text, flags=re.I)
        if match:
            os.environ[env_name] = match.group(1).strip()


def get_groq_keys(base_dir: Path) -> list[str]:
    keys: list[str] = []
    if os.environ.get("GROQ_API_KEY"):
        keys.append(os.environ["GROQ_API_KEY"])
    keys_path = base_dir / "keys"
    if keys_path.exists():
        text = keys_path.read_text(encoding="utf-8", errors="ignore")
        for match in re.finditer(r"gsk_[A-Za-z0-9]+", text):
            key = match.group(0).strip()
            if key not in keys:
                keys.append(key)
    return keys
