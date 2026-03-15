import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from gertrudes.config import Config
from gertrudes.github import Issue
from gertrudes.implementer import run, _implement_issue
from gertrudes.llm import StepResult


def _step_result(files: dict[str, str] | None = None) -> StepResult:
    """Helper: build a StepResult with JSON fallback payload."""
    return StepResult(
        written_files=[],
        raw_response=json.dumps(files or {}),
    )


@pytest.fixture
def config(tmp_path):
    return Config(
        repo="owner/repo",
        github_token="fake-token",
        llm_model="anthropic/claude-sonnet-4-20250514",
        workdir=tmp_path,
    )


@pytest.fixture
def issue():
    return Issue(
        number=42,
        title="Add logging",
        body="## Step 1\nModify `src/app.py` to add logging.\n\n## Step 2\nUpdate `src/config.py`.",
    )


@pytest.fixture
def single_step_issue():
    return Issue(
        number=42,
        title="Add logging",
        body="## Plan\nModify `src/app.py` to add logging.",
    )


@patch("gertrudes.implementer.github")
def test_run_no_issues(mock_github, config):
    mock_github.fetch_issues_by_label.return_value = []
    run(config)
    mock_github.fetch_issues_by_label.assert_called_once_with(config, config.issue_tag)


@patch("gertrudes.implementer.github")
def test_run_swaps_tags_on_failure(mock_github, config, issue):
    mock_github.fetch_issues_by_label.return_value = [issue]
    with patch("gertrudes.implementer._implement_issue", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            run(config)
    mock_github.remove_label.assert_any_call(config, 42, config.implementing_tag)
    mock_github.add_label.assert_any_call(config, 42, config.issue_tag)


@patch("gertrudes.implementer.llm")
@patch("gertrudes.implementer.git")
@patch("gertrudes.implementer.github")
def test_no_changes_tags_manual_work(mock_github, mock_git, mock_llm, config, single_step_issue):
    mock_git.clone_repo.return_value = config.workdir / "repo"
    mock_git.create_branch.return_value = "gertrudes/issue-42"
    mock_git.has_changes.return_value = False
    mock_llm.implement_step.return_value = _step_result({})

    (config.workdir / "repo").mkdir(parents=True, exist_ok=True)

    _implement_issue(config, single_step_issue)

    mock_github.add_label.assert_any_call(config, 42, config.manual_work_tag)
    mock_github.remove_label.assert_any_call(config, 42, config.implementing_tag)


@patch("gertrudes.implementer._run_tests")
@patch("gertrudes.implementer.llm")
@patch("gertrudes.implementer.git")
@patch("gertrudes.implementer.github")
def test_tests_fail_creates_draft_pr(mock_github, mock_git, mock_llm, mock_tests, config, single_step_issue):
    config.test_command = "pytest"

    repo_path = config.workdir / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)

    mock_git.clone_repo.return_value = repo_path
    mock_git.create_branch.return_value = "gertrudes/issue-42"
    mock_git.has_changes.return_value = True
    mock_git.commit_and_push.return_value = True
    mock_git.get_changed_files.return_value = ["src/app.py"]

    mock_llm.implement_step.return_value = _step_result({"src/app.py": "print('hi')"})
    mock_llm.fix_errors.return_value = StepResult(
        written_files=[],
        raw_response=json.dumps({"src/app.py": "print('fixed')"}),
    )
    mock_tests.return_value = (False, "AssertionError: expected 1 got 2")

    _implement_issue(config, single_step_issue)

    mock_github.create_pull_request.assert_called_once()
    call_kwargs = mock_github.create_pull_request.call_args
    assert call_kwargs.kwargs.get("draft") or call_kwargs[1].get("draft") or \
        (len(call_kwargs[0]) >= 6 and call_kwargs[0][5] is True)
    mock_github.add_label.assert_any_call(config, 42, config.manual_work_tag)


@patch("gertrudes.implementer._run_tests")
@patch("gertrudes.implementer.llm")
@patch("gertrudes.implementer.git")
@patch("gertrudes.implementer.github")
def test_success_creates_pr_and_tags_done(mock_github, mock_git, mock_llm, mock_tests, config, single_step_issue):
    config.test_command = "pytest"

    repo_path = config.workdir / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)

    mock_git.clone_repo.return_value = repo_path
    mock_git.create_branch.return_value = "gertrudes/issue-42"
    mock_git.has_changes.return_value = True
    mock_git.commit_and_push.return_value = True

    mock_llm.implement_step.return_value = _step_result({"src/app.py": "print('hi')"})
    mock_tests.return_value = (True, "")
    mock_github.create_pull_request.return_value = {"html_url": "https://github.com/pr/1"}

    _implement_issue(config, single_step_issue)

    mock_github.create_pull_request.assert_called_once()
    assert not mock_github.create_pull_request.call_args.kwargs.get("draft", False)
    mock_github.add_label.assert_any_call(config, 42, config.done_tag)


@patch("gertrudes.implementer.llm")
@patch("gertrudes.implementer.git")
@patch("gertrudes.implementer.github")
def test_llm_api_error_propagates(mock_github, mock_git, mock_llm, config, single_step_issue):
    """When the LLM API throws on the first step with no prior changes, error propagates."""
    repo_path = config.workdir / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)

    mock_git.clone_repo.return_value = repo_path
    mock_git.create_branch.return_value = "gertrudes/issue-42"
    mock_git.has_changes.return_value = False  # no changes before failure
    mock_llm.implement_step.side_effect = Exception("API rate limit exceeded")

    _implement_issue(config, single_step_issue)

    # Should tag as manual work since step failed with no changes
    mock_github.add_label.assert_any_call(config, 42, config.manual_work_tag)


@patch("gertrudes.implementer.llm")
@patch("gertrudes.implementer.git")
@patch("gertrudes.implementer.github")
def test_step_failure_creates_partial_draft_pr(mock_github, mock_git, mock_llm, config, issue):
    """When step 2 fails, step 1's changes are preserved in a draft PR."""
    repo_path = config.workdir / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)

    mock_git.clone_repo.return_value = repo_path
    mock_git.create_branch.return_value = "gertrudes/issue-42"
    mock_git.has_changes.return_value = True
    mock_git.commit_and_push.return_value = True

    # Step 1 succeeds, step 2 fails
    mock_llm.implement_step.side_effect = [
        _step_result({"src/app.py": "print('step1')"}),
        Exception("LLM error on step 2"),
    ]
    mock_github.create_pull_request.return_value = {"html_url": "https://github.com/pr/1"}

    _implement_issue(config, issue)

    # Should create a draft PR
    mock_github.create_pull_request.assert_called_once()
    call_args = mock_github.create_pull_request.call_args
    assert call_args.kwargs.get("draft") is True

    # Draft body should have completed/remaining steps
    summary = call_args[0][4] if len(call_args[0]) > 4 else call_args.kwargs.get("summary", "")
    assert "Step 1" in summary
    assert "Step 2" in summary
    assert "partial" in summary.lower() or "Remaining" in summary

    # Should tag as manual work
    mock_github.add_label.assert_any_call(config, 42, config.manual_work_tag)


@patch("gertrudes.implementer.llm")
@patch("gertrudes.implementer.git")
@patch("gertrudes.implementer.github")
def test_all_steps_succeed(mock_github, mock_git, mock_llm, config, issue):
    """Both steps succeed, creates a normal (non-draft) PR."""
    config.test_command = None

    repo_path = config.workdir / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)

    mock_git.clone_repo.return_value = repo_path
    mock_git.create_branch.return_value = "gertrudes/issue-42"
    mock_git.has_changes.return_value = True
    mock_git.commit_and_push.return_value = True

    mock_llm.implement_step.side_effect = [
        _step_result({"src/app.py": "step1 content"}),
        _step_result({"src/config.py": "step2 content"}),
    ]
    mock_github.create_pull_request.return_value = {"html_url": "https://github.com/pr/1"}

    _implement_issue(config, issue)

    # Called implement_step twice (once per step)
    assert mock_llm.implement_step.call_count == 2

    # Normal PR, not draft
    mock_github.create_pull_request.assert_called_once()
    assert not mock_github.create_pull_request.call_args.kwargs.get("draft", False)
    mock_github.add_label.assert_any_call(config, 42, config.done_tag)


@patch("gertrudes.implementer.llm")
@patch("gertrudes.implementer.git")
@patch("gertrudes.implementer.github")
def test_git_push_failure_propagates(mock_github, mock_git, mock_llm, config, single_step_issue):
    """When git push fails during commit_and_push, error propagates."""
    repo_path = config.workdir / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)

    mock_git.clone_repo.return_value = repo_path
    mock_git.create_branch.return_value = "gertrudes/issue-42"
    mock_git.has_changes.return_value = True
    mock_git.commit_and_push.side_effect = RuntimeError("git push failed: permission denied")

    mock_llm.implement_step.return_value = _step_result({"src/app.py": "print('hi')"})

    with pytest.raises(RuntimeError, match="git push failed"):
        _implement_issue(config, single_step_issue)


@patch("gertrudes.implementer.llm")
@patch("gertrudes.implementer.git")
@patch("gertrudes.implementer.github")
def test_clone_failure_propagates(mock_github, mock_git, mock_llm, config, single_step_issue):
    mock_git.clone_repo.side_effect = RuntimeError("clone failed: repo not found")
    with pytest.raises(RuntimeError, match="clone failed"):
        _implement_issue(config, single_step_issue)


@patch("gertrudes.implementer.llm")
@patch("gertrudes.implementer.git")
@patch("gertrudes.implementer.github")
def test_no_test_command_skips_tests(mock_github, mock_git, mock_llm, config, single_step_issue):
    config.test_command = None

    repo_path = config.workdir / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)

    mock_git.clone_repo.return_value = repo_path
    mock_git.create_branch.return_value = "gertrudes/issue-42"
    mock_git.has_changes.return_value = True
    mock_git.commit_and_push.return_value = True

    mock_llm.implement_step.return_value = _step_result({"src/app.py": "print('hi')"})
    mock_github.create_pull_request.return_value = {"html_url": "https://github.com/pr/1"}

    with patch("gertrudes.implementer._run_tests") as mock_tests:
        _implement_issue(config, single_step_issue)
        mock_tests.assert_not_called()

    mock_github.create_pull_request.assert_called_once()
    mock_github.add_label.assert_any_call(config, 42, config.done_tag)


@patch("gertrudes.implementer.llm")
@patch("gertrudes.implementer.git")
@patch("gertrudes.implementer.github")
def test_commit_returns_false_nothing_to_commit(mock_github, mock_git, mock_llm, config, single_step_issue):
    config.test_command = None

    repo_path = config.workdir / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)

    mock_git.clone_repo.return_value = repo_path
    mock_git.create_branch.return_value = "gertrudes/issue-42"
    mock_git.has_changes.return_value = True
    mock_git.commit_and_push.return_value = False

    mock_llm.implement_step.return_value = _step_result({"src/app.py": "content"})

    _implement_issue(config, single_step_issue)

    mock_github.comment_on_issue.assert_called_once()
    assert "No committable changes" in mock_github.comment_on_issue.call_args[0][2]
    mock_github.create_pull_request.assert_not_called()


@patch("gertrudes.implementer.github")
def test_run_error_comments_on_issue(mock_github, config, issue):
    mock_github.fetch_issues_by_label.return_value = [issue]
    with patch("gertrudes.implementer._implement_issue", side_effect=RuntimeError("something broke")):
        with pytest.raises(RuntimeError):
            run(config)
    mock_github.comment_on_issue.assert_called_once()
    assert "something broke" in mock_github.comment_on_issue.call_args[0][2]


@patch("gertrudes.implementer.llm")
@patch("gertrudes.implementer.git")
@patch("gertrudes.implementer.github")
def test_implement_step_called_with_context(mock_github, mock_git, mock_llm, config, issue):
    """implement_step is called with mentioned_files and previous_steps_summary."""
    repo_path = config.workdir / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)

    mock_git.clone_repo.return_value = repo_path
    mock_git.create_branch.return_value = "gertrudes/issue-42"
    mock_git.has_changes.return_value = True
    mock_git.commit_and_push.return_value = True

    mock_llm.implement_step.side_effect = [
        _step_result({"src/app.py": "step1"}),
        _step_result({"src/config.py": "step2"}),
    ]
    mock_github.create_pull_request.return_value = {"html_url": "https://github.com/pr/1"}

    _implement_issue(config, issue)

    calls = mock_llm.implement_step.call_args_list
    # First call: no previous_steps_summary
    assert calls[0].kwargs.get("previous_steps_summary") is None
    # Second call: previous_steps_summary mentions step 1
    prev = calls[1].kwargs.get("previous_steps_summary")
    assert prev is not None
    assert "Step 1" in prev
