import subprocess

import pytest

from gertrudes.git import (
    create_branch,
    has_changes,
    get_changed_files,
    commit_and_push,
    reset_and_cleanup,
)


@pytest.fixture
def git_repo(tmp_path):
    """Create a real git repo with an initial commit."""
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
    # Initial commit
    (tmp_path / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)
    return tmp_path


def test_create_branch(git_repo):
    name = create_branch(git_repo, "feature/test")
    assert name == "feature/test"
    result = subprocess.run(
        ["git", "branch", "--show-current"], cwd=git_repo, capture_output=True, text=True
    )
    assert result.stdout.strip() == "feature/test"


def test_has_changes_false_when_clean(git_repo):
    assert has_changes(git_repo) is False


def test_has_changes_true_with_modified_file(git_repo):
    (git_repo / "README.md").write_text("# Changed")
    assert has_changes(git_repo) is True


def test_has_changes_true_with_untracked_file(git_repo):
    (git_repo / "new_file.py").write_text("hello")
    assert has_changes(git_repo) is True


def test_get_changed_files_modified(git_repo):
    (git_repo / "README.md").write_text("# Changed")
    files = get_changed_files(git_repo)
    assert "README.md" in files


def test_get_changed_files_untracked(git_repo):
    (git_repo / "new.py").write_text("new")
    files = get_changed_files(git_repo)
    assert "new.py" in files


def test_get_changed_files_empty_when_clean(git_repo):
    files = get_changed_files(git_repo)
    assert files == []


def test_commit_and_push_returns_false_when_clean(git_repo):
    # No remote, but commit_and_push should return False before push
    result = commit_and_push(git_repo, "main", "nothing")
    assert result is False


def test_commit_and_push_commits_changes(git_repo):
    (git_repo / "new.py").write_text("content")
    # commit_and_push will fail at push (no remote), but we can test the commit part
    with pytest.raises(RuntimeError, match="push"):
        commit_and_push(git_repo, "main", "add new file")
    # Verify the commit was made before push failed
    result = subprocess.run(
        ["git", "log", "--oneline", "-1"], cwd=git_repo, capture_output=True, text=True
    )
    assert "add new file" in result.stdout


def test_reset_and_cleanup(git_repo):
    create_branch(git_repo, "feature/to-delete")
    (git_repo / "dirty.py").write_text("dirty")
    subprocess.run(["git", "add", "-A"], cwd=git_repo, capture_output=True)

    reset_and_cleanup(git_repo, "main", "feature/to-delete")

    # Should be back on main
    result = subprocess.run(
        ["git", "branch", "--show-current"], cwd=git_repo, capture_output=True, text=True
    )
    assert result.stdout.strip() == "main"

    # Feature branch should be deleted
    result = subprocess.run(
        ["git", "branch"], cwd=git_repo, capture_output=True, text=True
    )
    assert "feature/to-delete" not in result.stdout

    # Dirty file should be gone
    assert not (git_repo / "dirty.py").exists()
