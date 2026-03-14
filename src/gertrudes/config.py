"""Configuration loading: YAML file + environment variables."""

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class Config:
    repo: str
    llm_model: str = "anthropic/claude-sonnet-4-20250514"
    github_token: str = ""
    issue_tag: str = "ready-to-implement"
    implementing_tag: str = "implementing"
    done_tag: str = "implemented"
    manual_work_tag: str = "manual-work"
    pr_label: str = "automated-pr"
    base_branch: str = "main"
    build_command: str | None = None
    build_workdir: str = "."
    test_command: str | None = None
    test_workdir: str = "."
    max_fix_retries: int = 2
    workdir: Path | None = None
    system_prompt: str | None = None


def load_config(config_path: str | None = None) -> Config:
    """Load config from YAML file, then override with env vars."""
    # Find config file
    if config_path:
        path = Path(config_path)
    else:
        path = Path("gertrudes.yaml")
        if not path.exists():
            path = Path("gertrudes.yml")

    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}. "
            "Create a gertrudes.yaml or pass --config."
        )

    with open(path) as f:
        data = yaml.safe_load(f) or {}

    # Build config from file
    workdir = data.get("workdir")
    config = Config(
        repo=data["repo"],
        llm_model=data.get("llm_model", Config.llm_model),
        issue_tag=data.get("issue_tag", Config.issue_tag),
        implementing_tag=data.get("implementing_tag", Config.implementing_tag),
        done_tag=data.get("done_tag", Config.done_tag),
        manual_work_tag=data.get("manual_work_tag", Config.manual_work_tag),
        pr_label=data.get("pr_label", Config.pr_label),
        base_branch=data.get("base_branch", Config.base_branch),
        build_command=data.get("build_command"),
        build_workdir=data.get("build_workdir", "."),
        test_command=data.get("test_command"),
        test_workdir=data.get("test_workdir", "."),
        max_fix_retries=data.get("max_fix_retries", Config.max_fix_retries),
        workdir=Path(workdir) if workdir else None,
        system_prompt=data.get("system_prompt"),
    )

    # Load .env file if present
    load_dotenv()

    # Env var overrides
    config.github_token = os.environ.get("GITHUB_TOKEN", "")
    if not config.github_token:
        raise EnvironmentError("GITHUB_TOKEN environment variable is required.")

    if env_model := os.environ.get("LLM_MODEL"):
        config.llm_model = env_model

    return config
