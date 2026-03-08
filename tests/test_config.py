import os

import pytest

from gertrudes.config import load_config


def test_load_config_from_yaml(tmp_path, monkeypatch):
    config_file = tmp_path / "gertrudes.yaml"
    config_file.write_text(
        'repo: "owner/repo"\n'
        'llm_model: "openai/gpt-4o"\n'
        'issue_tag: "todo"\n'
    )
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    monkeypatch.chdir(tmp_path)

    config = load_config(str(config_file))
    assert config.repo == "owner/repo"
    assert config.llm_model == "openai/gpt-4o"
    assert config.issue_tag == "todo"
    assert config.github_token == "fake-token"


def test_defaults_are_used(tmp_path, monkeypatch):
    config_file = tmp_path / "gertrudes.yaml"
    config_file.write_text('repo: "owner/repo"\n')
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")

    config = load_config(str(config_file))
    assert config.base_branch == "main"
    assert config.max_fix_retries == 2
    assert config.implementing_tag == "implementing"
    assert config.manual_work_tag == "manual-work"


def test_env_var_overrides_llm_model(tmp_path, monkeypatch):
    config_file = tmp_path / "gertrudes.yaml"
    config_file.write_text('repo: "owner/repo"\nllm_model: "anthropic/claude-sonnet-4-20250514"\n')
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("LLM_MODEL", "mistral/codestral-latest")

    config = load_config(str(config_file))
    assert config.llm_model == "mistral/codestral-latest"


def test_missing_github_token_raises(tmp_path, monkeypatch):
    config_file = tmp_path / "gertrudes.yaml"
    config_file.write_text('repo: "owner/repo"\n')
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    with pytest.raises(EnvironmentError, match="GITHUB_TOKEN"):
        load_config(str(config_file))


def test_missing_config_file_raises():
    with pytest.raises(FileNotFoundError, match="Config file not found"):
        load_config("/nonexistent/path.yaml")
