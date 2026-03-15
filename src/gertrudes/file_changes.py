"""Parse LLM JSON responses into file changes and write them to disk."""

from __future__ import annotations

import json
import re
from pathlib import Path

from gertrudes.sandbox import safe_resolve


def parse_llm_response(raw: str) -> dict[str, str]:
    """Parse an LLM response into a {filepath: content} dict.

    Handles:
    1. Clean JSON object
    2. JSON wrapped in ```json ... ``` fences
    3. JSON wrapped in plain ``` ... ``` fences
    """
    text = raw.strip()

    # Try direct JSON parse first
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Try extracting from code fences
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if fence_match:
        try:
            result = json.loads(fence_match.group(1).strip())
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse LLM response as JSON:\n{text[:500]}")


def apply_changes(repo_path: Path, changes: dict[str, str]) -> list[str]:
    """Write file changes to disk. Returns list of written paths."""
    written = []
    for rel_path, content in changes.items():
        file_path = safe_resolve(repo_path, rel_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        written.append(rel_path)
    return written
