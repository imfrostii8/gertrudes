"""Local git operations: clone, branch, commit, push."""

import subprocess
from pathlib import Path


def _run(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{result.stderr}")
    return result


def clone_repo(repo: str, token: str, dest: Path, branch: str = "main") -> Path:
    """Shallow-clone a GitHub repo into dest and checkout the given branch."""
    url = f"https://x-access-token:{token}@github.com/{repo}.git"
    subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", branch, url, str(dest)],
        capture_output=True,
        text=True,
        check=True,
    )
    return dest


def create_branch(repo_path: Path, branch_name: str) -> str:
    _run(["checkout", "-b", branch_name], cwd=repo_path)
    return branch_name


def has_changes(repo_path: Path) -> bool:
    result = _run(["diff", "--stat"], cwd=repo_path, check=False)
    untracked = _run(
        ["ls-files", "--others", "--exclude-standard"], cwd=repo_path, check=False
    )
    return bool(result.stdout.strip() or untracked.stdout.strip())


def get_changed_files(repo_path: Path) -> list[str]:
    """Return list of files changed relative to HEAD."""
    result = _run(["diff", "--name-only", "HEAD"], cwd=repo_path, check=False)
    staged = _run(["diff", "--name-only", "--cached"], cwd=repo_path, check=False)
    untracked = _run(
        ["ls-files", "--others", "--exclude-standard"], cwd=repo_path, check=False
    )
    files = set()
    for output in [result.stdout, staged.stdout, untracked.stdout]:
        files.update(l.strip() for l in output.splitlines() if l.strip())
    return sorted(files)


def commit_and_push(repo_path: Path, branch: str, message: str) -> bool:
    """Stage all, commit, and push. Returns False if nothing to commit."""
    _run(["add", "-A"], cwd=repo_path)
    result = _run(["diff", "--cached", "--quiet"], cwd=repo_path, check=False)
    if result.returncode == 0:
        return False
    _run(["commit", "-m", message], cwd=repo_path)
    _run(["push", "-u", "origin", branch], cwd=repo_path)
    return True


def reset_and_cleanup(repo_path: Path, base_branch: str, feature_branch: str):
    """Reset to HEAD, switch back to base, delete the feature branch."""
    _run(["reset", "--hard", "HEAD"], cwd=repo_path)
    _run(["checkout", base_branch], cwd=repo_path)
    _run(["branch", "-D", feature_branch], cwd=repo_path, check=False)
