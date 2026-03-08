import json

import pytest
import responses

from gertrudes.config import Config
from gertrudes.github import (
    fetch_issues_by_label,
    add_label,
    remove_label,
    comment_on_issue,
    create_pull_request,
)


@pytest.fixture
def config():
    return Config(
        repo="owner/repo",
        github_token="fake-token",
    )


API = "https://api.github.com/repos/owner/repo"


@responses.activate
def test_fetch_issues_returns_issues(config):
    responses.get(
        f"{API}/issues",
        json=[
            {"number": 1, "title": "Issue 1", "body": "body1"},
            {"number": 2, "title": "Issue 2", "body": "body2"},
        ],
    )
    issues = fetch_issues_by_label(config, "ready")
    assert len(issues) == 2
    assert issues[0].number == 1
    assert issues[1].title == "Issue 2"


@responses.activate
def test_fetch_issues_skips_pull_requests(config):
    responses.get(
        f"{API}/issues",
        json=[
            {"number": 1, "title": "Issue", "body": "real issue"},
            {"number": 2, "title": "PR", "body": "a PR", "pull_request": {"url": "..."}},
        ],
    )
    issues = fetch_issues_by_label(config, "ready")
    assert len(issues) == 1
    assert issues[0].number == 1


@responses.activate
def test_fetch_issues_empty_body_defaults(config):
    responses.get(
        f"{API}/issues",
        json=[{"number": 1, "title": "No body", "body": None}],
    )
    issues = fetch_issues_by_label(config, "ready")
    assert issues[0].body == ""


@responses.activate
def test_fetch_issues_raises_on_error(config):
    responses.get(f"{API}/issues", status=500, json={"message": "Internal Server Error"})
    with pytest.raises(Exception):
        fetch_issues_by_label(config, "ready")


@responses.activate
def test_add_label(config):
    # Ensure label creation + apply
    responses.post(f"{API}/labels", json={})
    responses.post(f"{API}/issues/42/labels", json={})

    add_label(config, 42, "my-label")

    assert len(responses.calls) == 2
    # Check label creation payload
    assert json.loads(responses.calls[0].request.body)["name"] == "my-label"
    # Check label apply payload
    assert json.loads(responses.calls[1].request.body)["labels"] == ["my-label"]


@responses.activate
def test_remove_label(config):
    responses.delete(f"{API}/issues/42/labels/old-label", json={})
    remove_label(config, 42, "old-label")
    assert len(responses.calls) == 1


@responses.activate
def test_comment_on_issue(config):
    responses.post(f"{API}/issues/42/comments", json={})
    comment_on_issue(config, 42, "Hello!")
    assert json.loads(responses.calls[0].request.body)["body"] == "Hello!"


@responses.activate
def test_create_pull_request_success(config):
    responses.post(
        f"{API}/pulls",
        json={"number": 99, "html_url": "https://github.com/owner/repo/pull/99"},
    )
    responses.post(f"{API}/issues/99/labels", json={})

    pr = create_pull_request(config, "gertrudes/issue-42", 42, "Add feature", "- `app.py`")

    assert pr["html_url"] == "https://github.com/owner/repo/pull/99"
    payload = json.loads(responses.calls[0].request.body)
    assert payload["draft"] is False
    assert payload["base"] == "main"
    assert "Closes #42" in payload["body"]


@responses.activate
def test_create_pull_request_draft(config):
    responses.post(
        f"{API}/pulls",
        json={"number": 100, "html_url": "https://github.com/owner/repo/pull/100"},
    )
    responses.post(f"{API}/issues/100/labels", json={})

    pr = create_pull_request(config, "gertrudes/issue-42", 42, "Fix bug", "changes", draft=True)

    payload = json.loads(responses.calls[0].request.body)
    assert payload["draft"] is True


@responses.activate
def test_create_pull_request_failure_raises(config):
    responses.post(
        f"{API}/pulls",
        status=422,
        json={"message": "Validation Failed"},
    )
    with pytest.raises(RuntimeError, match="PR creation failed 422"):
        create_pull_request(config, "branch", 42, "Title", "summary")


@responses.activate
def test_auth_header_is_set(config):
    responses.get(f"{API}/issues", json=[])
    fetch_issues_by_label(config, "label")
    assert responses.calls[0].request.headers["Authorization"] == "token fake-token"
