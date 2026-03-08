"""LLM interaction via litellm for implementing plans and fixing errors."""

from __future__ import annotations

import litellm

from gertrudes.config import Config


def implement_step(
    config: Config,
    step_title: str,
    step_body: str,
    full_plan: str,
    files_content: dict[str, str],
) -> str:
    """Send a single step of the plan to the LLM, return raw response text."""
    files_text = ""
    for path, content in files_content.items():
        files_text += f"\n\n=== {path} ===\n{content}"

    prompt = f"""You are a software engineer implementing ONE step of a larger plan.

## Full Plan (for context)

{full_plan}

## Current Step: {step_title}

{step_body}

## Current File Contents
{files_text if files_text else "(No existing files provided — all files mentioned may be new.)"}

## Instructions

1. Implement ONLY the changes described in the "Current Step" section above.
2. For each file you modify or create, provide the COMPLETE new file content.
3. Do NOT implement changes from other steps — only this one.
4. Follow the existing code style and conventions.

## Response Format

Return ONLY a JSON object mapping file paths (relative to repo root) to their complete new content.
No markdown fences, no explanation, no preamble. Example:
{{"src/utils.py": "import os\\n...", "src/new_module.py": "..."}}

If this step requires no file changes, return an empty JSON object: {{}}"""

    response = litellm.completion(
        model=config.llm_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )
    return response.choices[0].message.content.strip()


def fix_errors(
    config: Config,
    error_output: str,
    files_content: dict[str, str],
) -> str:
    """Ask the LLM to fix build/test errors. Returns raw response text."""
    files_text = ""
    for path, content in files_content.items():
        files_text += f"\n\n=== {path} ===\n{content}"

    prompt = f"""The following files were just modified but the build/tests are failing.

## Error Output

{error_output}

## Current File Contents
{files_text}

## Instructions

Fix ONLY the errors shown above. Do not make any other changes.
Return ONLY a JSON object mapping each fixed file path to its complete new content.
No markdown fences, no explanation, no preamble."""

    response = litellm.completion(
        model=config.llm_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )
    return response.choices[0].message.content.strip()
