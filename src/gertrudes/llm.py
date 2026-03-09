"""LLM interaction via litellm for implementing plans and fixing errors."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import litellm

from gertrudes.config import Config

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List all tracked files in the repository.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file in the repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to the repo root.",
                    }
                },
                "required": ["path"],
            },
        },
    },
]

_MAX_TOOL_ROUNDS = 20


def _list_files(repo_path: Path) -> str:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or "(no tracked files found)"


def _read_file(repo_path: Path, path: str) -> str:
    full_path = repo_path / path
    if not full_path.exists():
        return f"File not found: {path}"
    try:
        return full_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return f"Error reading {path}: {e}"


def _run_tool(repo_path: Path, name: str, arguments: str) -> str:
    args = json.loads(arguments) if arguments else {}
    if name == "list_files":
        return _list_files(repo_path)
    if name == "read_file":
        return _read_file(repo_path, args["path"])
    return f"Unknown tool: {name}"


def implement_step(
    config: Config,
    step_title: str,
    step_body: str,
    full_plan: str,
    repo_path: Path,
) -> str:
    """Implement a single step using an agentic tool-calling loop."""
    prompt = f"""You are a software engineer implementing ONE step of a larger plan.

## Full Plan (for context)

{full_plan}

## Current Step: {step_title}

{step_body}

## Instructions

1. Use `list_files` to explore the repository structure.
2. Use `read_file` to read any files you need to understand before making changes.
3. Once you have enough context, implement ONLY the changes for the current step.
4. Follow the existing code style and conventions.

## Response Format

When ready, return ONLY a JSON object mapping file paths (relative to repo root) to their complete new content.
No markdown fences, no explanation, no preamble. Example:
{{"src/utils.py": "import os\\n...", "src/new_module.py": "..."}}

If this step requires no file changes, return an empty JSON object: {{}}"""

    messages = [{"role": "user", "content": prompt}]

    for _ in range(_MAX_TOOL_ROUNDS):
        response = litellm.completion(
            model=config.llm_model,
            messages=messages,
            tools=_TOOLS,
            temperature=0.1,
        )
        msg = response.choices[0].message

        if not msg.tool_calls:
            return msg.content.strip()

        # Append assistant message and execute each tool call
        messages.append(msg)
        for tool_call in msg.tool_calls:
            result = _run_tool(
                repo_path, tool_call.function.name, tool_call.function.arguments
            )
            print(
                f"  [tool] {tool_call.function.name}({tool_call.function.arguments[:80]}) -> {len(result)} chars"
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                }
            )

    raise RuntimeError(
        f"Exceeded {_MAX_TOOL_ROUNDS} tool rounds without a final answer."
    )


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
