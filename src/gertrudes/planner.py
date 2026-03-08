"""Extract file paths and steps from a markdown implementation plan."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Step:
    title: str
    body: str
    mentioned_files: list[str]


@dataclass
class Plan:
    raw_markdown: str
    mentioned_files: list[str]
    steps: list[Step]


# Matches paths like src/foo/bar.py, lib/utils.ts, etc.
_FILE_PATH_RE = re.compile(
    r"""
    (?:^|\s|`|\[|\()                # preceded by whitespace, backtick, bracket, or paren
    (
        (?:[\w\-./]+/)*             # optional directory parts
        [\w\-]+                     # filename stem
        \.[\w]+                     # extension
    )
    (?:\s|$|`|\]|\)|,|:)            # followed by whitespace, backtick, bracket, etc.
    """,
    re.VERBOSE | re.MULTILINE,
)

# Common non-code extensions to ignore
_IGNORE_EXTENSIONS = {
    ".md",
    ".txt",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".lock",
}

# Matches markdown headers (## or ###)
_HEADER_RE = re.compile(r"^(#{2,3})\s+(.+)$", re.MULTILINE)


def _extract_files(text: str) -> list[str]:
    """Extract file paths from a block of markdown text."""
    matches = _FILE_PATH_RE.findall(text)
    seen = set()
    files = []
    for match in matches:
        path = match.strip()
        ext = "." + path.rsplit(".", 1)[-1] if "." in path else ""
        if path not in seen and ext.lower() not in _IGNORE_EXTENSIONS:
            seen.add(path)
            files.append(path)
    return files


def _split_into_steps(body: str) -> list[Step]:
    """Split markdown into steps by ## or ### headers."""
    headers = list(_HEADER_RE.finditer(body))

    if not headers:
        # No headers — treat the whole body as one step
        files = _extract_files(body)
        return [Step(title="Full plan", body=body.strip(), mentioned_files=files)]

    steps = []
    for i, match in enumerate(headers):
        title = match.group(2).strip()
        start = match.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(body)
        section_body = body[start:end].strip()

        # Skip empty sections or non-implementation sections
        if not section_body:
            continue

        files = _extract_files(section_body)
        steps.append(Step(title=title, body=section_body, mentioned_files=files))

    # If no steps were created (all sections empty), fall back to full plan
    if not steps:
        files = _extract_files(body)
        return [Step(title="Full plan", body=body.strip(), mentioned_files=files)]

    return steps


def parse_plan(issue_body: str) -> Plan:
    """Parse a markdown issue body into a Plan with steps."""
    all_files = _extract_files(issue_body)
    steps = _split_into_steps(issue_body)

    return Plan(
        raw_markdown=issue_body,
        mentioned_files=all_files,
        steps=steps,
    )
