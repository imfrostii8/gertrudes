"""LLM interaction via litellm for implementing plans and fixing errors."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import litellm

from gertrudes.config import Config
from gertrudes.sandbox import safe_resolve

_MAX_FILE_SIZE = 50_000  # chars before truncation

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
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search for a pattern in the repository using git grep.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "The regex pattern to search for.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Optional file or directory path to restrict the search.",
                    },
                    "include": {
                        "type": "string",
                        "description": "Optional glob pattern to filter files, e.g. '*.py'.",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file, creating it or overwriting it entirely.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to the repo root.",
                    },
                    "content": {
                        "type": "string",
                        "description": "The full content to write to the file.",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Make a targeted find-and-replace edit in an existing file. "
                "The old_str must appear exactly once in the file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to the repo root.",
                    },
                    "old_str": {
                        "type": "string",
                        "description": "The exact string to find (must be unique in the file).",
                    },
                    "new_str": {
                        "type": "string",
                        "description": "The string to replace it with.",
                    },
                },
                "required": ["path", "old_str", "new_str"],
            },
        },
    },
]

_MAX_TOOL_ROUNDS = 20


@dataclass
class StepResult:
    written_files: list[str] = field(default_factory=list)
    raw_response: str = ""


def _list_files(repo_path: Path) -> str:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or "(no tracked files found)"


def _read_file(repo_path: Path, path: str) -> str:
    try:
        full_path = safe_resolve(repo_path, path)
    except ValueError as e:
        return f"Access denied: {e}"
    if not full_path.exists():
        return f"File not found: {path}"
    try:
        content = full_path.read_text(encoding="utf-8", errors="ignore")
        if len(content) > _MAX_FILE_SIZE:
            content = content[:_MAX_FILE_SIZE] + "\n... (truncated)"
        return content
    except Exception as e:
        return f"Error reading {path}: {e}"


def _search_code(
    repo_path: Path,
    pattern: str,
    path: str | None = None,
    include: str | None = None,
) -> str:
    cmd = ["git", "grep", "-n", pattern]
    if include:
        cmd.extend(["--", include])
    elif path:
        cmd.extend(["--", path])
    result = subprocess.run(
        cmd,
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    output = result.stdout.strip()
    return output or f"No matches found for: {pattern}"


def _write_file(
    repo_path: Path,
    path: str,
    content: str,
    written_files: list[str],
) -> str:
    try:
        file_path = safe_resolve(repo_path, path)
    except ValueError as e:
        return f"Access denied: {e}"
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        if path not in written_files:
            written_files.append(path)
        return f"Written: {path}"
    except Exception as e:
        return f"Error writing {path}: {e}"


def _edit_file(
    repo_path: Path,
    path: str,
    old_str: str,
    new_str: str,
    written_files: list[str],
) -> str:
    try:
        file_path = safe_resolve(repo_path, path)
    except ValueError as e:
        return f"Access denied: {e}"
    if not file_path.exists():
        return f"File not found: {path}"
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        count = content.count(old_str)
        if count == 0:
            return f"String not found in {path}"
        if count > 1:
            return f"String found {count} times in {path} — must be unique for safe replacement"
        new_content = content.replace(old_str, new_str, 1)
        file_path.write_text(new_content, encoding="utf-8")
        if path not in written_files:
            written_files.append(path)
        return f"Edited: {path}"
    except Exception as e:
        return f"Error editing {path}: {e}"


def _run_tool(
    repo_path: Path,
    name: str,
    arguments: str,
    written_files: list[str],
) -> str:
    args = json.loads(arguments) if arguments else {}
    if name == "list_files":
        return _list_files(repo_path)
    if name == "read_file":
        return _read_file(repo_path, args["path"])
    if name == "search_code":
        return _search_code(
            repo_path,
            args["pattern"],
            args.get("path"),
            args.get("include"),
        )
    if name == "write_file":
        return _write_file(repo_path, args["path"], args["content"], written_files)
    if name == "edit_file":
        return _edit_file(
            repo_path, args["path"], args["old_str"], args["new_str"], written_files
        )
    return f"Unknown tool: {name}"


def _read_context_files(repo_path: Path, file_paths: list[str]) -> str:
    """Read files and format as context blocks, truncating large files."""
    blocks = []
    for path in file_paths:
        try:
            full_path = safe_resolve(repo_path, path)
        except ValueError:
            continue
        if not full_path.exists():
            continue
        try:
            content = full_path.read_text(encoding="utf-8", errors="ignore")
            if len(content) > _MAX_FILE_SIZE:
                content = content[:_MAX_FILE_SIZE] + "\n... (truncated)"
            blocks.append(f"=== {path} ===\n{content}")
        except Exception:
            continue
    return "\n\n".join(blocks)


def _read_project_context(repo_path: Path) -> str:
    """Read CLAUDE.md and README.md if they exist."""
    return _read_context_files(repo_path, ["CLAUDE.md", "README.md"])


def _run_tool_loop(
    config: Config,
    repo_path: Path,
    messages: list[dict],
) -> StepResult:
    """Run the agentic tool-calling loop. Returns StepResult."""
    written_files: list[str] = []

    for _ in range(_MAX_TOOL_ROUNDS):
        response = litellm.completion(
            model=config.llm_model,
            messages=messages,
            tools=_TOOLS,
            temperature=0.1,
        )
        msg = response.choices[0].message

        if not msg.tool_calls:
            return StepResult(
                written_files=written_files,
                raw_response=msg.content.strip() if msg.content else "",
            )

        messages.append(msg)
        for tool_call in msg.tool_calls:
            result = _run_tool(
                repo_path,
                tool_call.function.name,
                tool_call.function.arguments,
                written_files,
            )
            print(
                f"  [tool] {tool_call.function.name}"
                f"({tool_call.function.arguments[:80]}) -> {len(result)} chars"
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


def implement_step(
    config: Config,
    step_title: str,
    step_body: str,
    full_plan: str,
    repo_path: Path,
    mentioned_files: list[str] | None = None,
    previous_steps_summary: str | None = None,
) -> StepResult:
    """Implement a single step using an agentic tool-calling loop."""
    messages: list[dict] = []

    # System message: system_prompt + project context (CLAUDE.md, README.md)
    system_parts = []
    if config.system_prompt:
        system_parts.append(config.system_prompt)
    project_context = _read_project_context(repo_path)
    if project_context:
        system_parts.append(project_context)
    if system_parts:
        messages.append({"role": "system", "content": "\n\n".join(system_parts)})

    # User message
    user_parts = []

    if mentioned_files:
        files_context = _read_context_files(repo_path, mentioned_files)
        if files_context:
            user_parts.append(f"## Referenced Files\n\n{files_context}")

    user_parts.append(f"## Full Plan (for context)\n\n{full_plan}")

    if previous_steps_summary:
        user_parts.append(
            f"## Previous Steps (already completed)\n\n{previous_steps_summary}"
        )

    user_parts.append(f"## Current Step: {step_title}\n\n{step_body}")

    user_parts.append(
        "## Instructions\n\n"
        "1. Use `list_files` to explore the repository structure.\n"
        "2. Use `read_file` to read any files you need, and `search_code` to find patterns.\n"
        "3. Implement ONLY the changes for the current step using `write_file` (for new or "
        "full-file rewrites) and `edit_file` (for targeted changes to existing files).\n"
        "4. Follow the existing code style and conventions.\n"
        "5. When done, respond with a brief summary of what you changed.\n\n"
        "If this step requires no file changes, just say so briefly."
    )

    messages.append({"role": "user", "content": "\n\n".join(user_parts)})

    return _run_tool_loop(config, repo_path, messages)


def fix_errors(
    config: Config,
    error_output: str,
    files_content: dict[str, str],
    repo_path: Path,
) -> StepResult:
    """Fix build/test errors using an agentic tool-calling loop."""
    files_text = ""
    for path, content in files_content.items():
        files_text += f"\n\n=== {path} ===\n{content}"

    messages: list[dict] = []

    if config.system_prompt:
        messages.append({"role": "system", "content": config.system_prompt})

    messages.append(
        {
            "role": "user",
            "content": (
                "The following files were just modified but the build/tests are failing.\n\n"
                f"## Error Output\n\n{error_output}\n\n"
                f"## Current File Contents (recently modified files)\n{files_text}\n\n"
                "## Instructions\n\n"
                "Fix ONLY the errors shown above. Do not make any other changes.\n\n"
                "1. Use `read_file` and `search_code` to explore context if needed.\n"
                "2. Use `write_file` to rewrite files and `edit_file` to make targeted fixes.\n"
                "3. When done, respond with a brief summary of what you fixed."
            ),
        }
    )

    return _run_tool_loop(config, repo_path, messages)
