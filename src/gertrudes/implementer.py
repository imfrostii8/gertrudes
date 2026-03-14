"""Core orchestrator: the main implementation flow."""

from __future__ import annotations

import random
import subprocess
import tempfile
from pathlib import Path

from gertrudes import file_changes, git, github, llm, planner
from gertrudes.config import Config


def run(config: Config):
    """Main entry point: fetch an issue, implement it, open a PR."""
    print(f"Fetching issues with tag '{config.issue_tag}' from {config.repo}...")
    issues = github.fetch_issues_by_label(config, config.issue_tag)

    if not issues:
        print("No issues found. Nothing to do.")
        return

    # Pick one randomly
    issue = random.choice(issues)
    print(f"Picked issue #{issue.number}: {issue.title}")

    # Swap tag to implementing
    github.remove_label(config, issue.number, config.issue_tag)
    github.add_label(config, issue.number, config.implementing_tag)

    try:
        _implement_issue(config, issue)
    except Exception as e:
        print(f"Failed: {e}")
        github.comment_on_issue(
            config,
            issue.number,
            f"gertrudes: Failed to implement this issue.\n```\n{e}\n```",
        )
        # Restore original tag
        github.remove_label(config, issue.number, config.implementing_tag)
        github.add_label(config, issue.number, config.issue_tag)
        raise


def _implement_issue(config: Config, issue: github.Issue):
    """Clone, implement step by step, test, push, and open a PR."""
    # Parse the plan into steps
    plan = planner.parse_plan(issue.body)
    print(
        f"Found {len(plan.steps)} step(s) and {len(plan.mentioned_files)} file(s) in the plan."
    )

    # Clone repo
    workdir = (
        Path(config.workdir)
        if config.workdir
        else Path(tempfile.mkdtemp(prefix="gertrudes-"))
    )
    repo_path = workdir / config.repo.split("/")[-1]
    print(f"Cloning {config.repo} into {repo_path}...")
    git.clone_repo(config.repo, config.github_token, repo_path, config.base_branch)

    # Create feature branch
    branch = f"gertrudes/issue-{issue.number}"
    git.create_branch(repo_path, branch)
    print(f"Created branch: {branch}")

    # Implement step by step
    all_written: list[str] = []
    completed_steps: list[str] = []
    failed_step: str | None = None
    failed_error: str | None = None
    remaining_steps: list[planner.Step] = []
    # Accumulates the current content of every file changed so far, passed to each new step
    previous_changes: dict[str, str] = {}

    for i, step in enumerate(plan.steps):
        print(f"\n--- Step {i + 1}/{len(plan.steps)}: {step.title} ---")

        try:
            raw_response = llm.implement_step(
                config,
                step.title,
                step.body,
                plan.raw_markdown,
                repo_path,
                mentioned_files=step.mentioned_files,
                previous_changes=previous_changes if previous_changes else None,
            )
            changes = file_changes.parse_llm_response(raw_response)
        except Exception as e:
            print(f"  Step failed: {e}")
            failed_step = step.title
            failed_error = str(e)
            remaining_steps = list(plan.steps[i:])
            break

        if changes:
            written = file_changes.apply_changes(repo_path, changes)
            all_written.extend(written)
            # Update previous_changes with the latest content of every touched file
            for path in written:
                full = repo_path / path
                if full.exists():
                    previous_changes[path] = full.read_text(encoding="utf-8", errors="ignore")
            print(f"  Applied: {', '.join(written)}")

        completed_steps.append(step.title)

    # Check if we have any changes at all
    if not git.has_changes(repo_path):
        if failed_step:
            github.comment_on_issue(
                config,
                issue.number,
                f'gertrudes: Failed at step "{failed_step}" with no prior changes.\n'
                f"```\n{failed_error}\n```",
            )
            github.remove_label(config, issue.number, config.implementing_tag)
            github.add_label(config, issue.number, config.manual_work_tag)
        else:
            github.comment_on_issue(
                config,
                issue.number,
                "gertrudes: LLM returned no file changes. Manual implementation needed.",
            )
            github.remove_label(config, issue.number, config.implementing_tag)
            github.add_label(config, issue.number, config.manual_work_tag)
        return

    # If a step failed but we have partial progress, create a draft PR
    if failed_step:
        _create_partial_pr(
            config,
            repo_path,
            branch,
            issue,
            all_written,
            completed_steps,
            failed_step,
            failed_error,
            remaining_steps,
        )
        return

    # All steps succeeded — run tests if configured
    if config.test_command:
        tests_passed, error_output = _run_tests(config.test_command, repo_path)
        for attempt in range(config.max_fix_retries):
            if tests_passed:
                break
            print(f"Fix attempt {attempt + 1}/{config.max_fix_retries}...")
            changed_files = git.get_changed_files(repo_path)
            current_content = {
                f: (repo_path / f).read_text(encoding="utf-8", errors="ignore")
                for f in changed_files
                if (repo_path / f).exists()
            }

            fix_response = llm.fix_errors(config, error_output, current_content)
            fix_changes = file_changes.parse_llm_response(fix_response)
            file_changes.apply_changes(repo_path, fix_changes)
            tests_passed, error_output = _run_tests(config.test_command, repo_path)

        if not tests_passed:
            # Create draft PR with test failure info
            commit_msg = (
                f"wip: implement issue #{issue.number} (tests failing)\n\n"
                f"{issue.title}"
            )
            committed = git.commit_and_push(repo_path, branch, commit_msg)
            if committed:
                summary = "\n".join(f"- `{f}`" for f in all_written)
                draft_body = (
                    f"{summary}\n\n"
                    f"---\n\n"
                    f"**Requires manual work.** Tests still failing after "
                    f"{config.max_fix_retries} fix attempts.\n\n"
                    f"### Errors\n\n"
                    f"```\n{error_output[:3000]}\n```"
                )
                pr = github.create_pull_request(
                    config,
                    branch,
                    issue.number,
                    issue.title,
                    draft_body,
                    draft=True,
                )
                print(f"Draft PR created: {pr['html_url']}")
                github.comment_on_issue(
                    config,
                    issue.number,
                    f"gertrudes: Tests failing after {config.max_fix_retries} fix attempts. "
                    f"Opened a draft PR for manual work: {pr['html_url']}",
                )
            github.remove_label(config, issue.number, config.implementing_tag)
            github.add_label(config, issue.number, config.manual_work_tag)
            return

    # Commit and push
    commit_msg = f"feat: implement issue #{issue.number}\n\n{issue.title}"
    committed = git.commit_and_push(repo_path, branch, commit_msg)

    if not committed:
        github.comment_on_issue(
            config,
            issue.number,
            "gertrudes: No committable changes produced.",
        )
        return

    # Create PR
    summary = "\n".join(f"- `{f}`" for f in all_written)
    pr = github.create_pull_request(config, branch, issue.number, issue.title, summary)
    print(f"PR created: {pr['html_url']}")

    # Comment on issue + swap tag to done
    github.comment_on_issue(
        config,
        issue.number,
        f"gertrudes: Implementation complete!\n\nPR: {pr['html_url']}",
    )
    github.remove_label(config, issue.number, config.implementing_tag)
    github.add_label(config, issue.number, config.done_tag)

    print(f"Done! Issue #{issue.number} -> PR {pr['html_url']}")


def _create_partial_pr(
    config: Config,
    repo_path: Path,
    branch: str,
    issue: github.Issue,
    written: list[str],
    completed_steps: list[str],
    failed_step: str,
    failed_error: str | None,
    remaining_steps: list[planner.Step],
):
    """Commit partial progress and open a draft PR with instructions."""
    commit_msg = (
        f"wip: implement issue #{issue.number} (partial)\n\n"
        f"{issue.title}\n\n"
        f"Completed {len(completed_steps)} of {len(completed_steps) + len(remaining_steps)} steps."
    )
    committed = git.commit_and_push(repo_path, branch, commit_msg)

    if not committed:
        github.comment_on_issue(
            config,
            issue.number,
            f'gertrudes: Failed at step "{failed_step}" with no committable changes.\n'
            f"```\n{failed_error}\n```",
        )
        github.remove_label(config, issue.number, config.implementing_tag)
        github.add_label(config, issue.number, config.manual_work_tag)
        return

    completed_list = "\n".join(f"- [x] {s}" for s in completed_steps)
    remaining_list = ""
    for s in remaining_steps:
        remaining_list += f"#### {s.title}\n\n{s.body}\n\n"
    files_list = "\n".join(f"- `{f}`" for f in written)

    draft_body = (
        f"### Completed steps\n\n{completed_list}\n\n"
        f"### Failed step\n\n"
        f"**{failed_step}**\n\n"
        f"```\n{failed_error[:2000] if failed_error else 'Unknown error'}\n```\n\n"
        f"### Remaining steps (instructions for agent)\n\n{remaining_list}"
        f"### Files changed so far\n\n{files_list}\n\n"
        f"---\n\n"
        f"**This PR has partial progress.** An agent or developer needs to "
        f"continue from the failed step above."
    )

    pr = github.create_pull_request(
        config,
        branch,
        issue.number,
        issue.title,
        draft_body,
        draft=True,
    )
    print(f"Draft PR created (partial): {pr['html_url']}")

    github.comment_on_issue(
        config,
        issue.number,
        f"gertrudes: Completed {len(completed_steps)}/{len(completed_steps) + len(remaining_steps)} steps. "
        f'Failed at "{failed_step}". '
        f"Draft PR with partial progress: {pr['html_url']}",
    )
    github.remove_label(config, issue.number, config.implementing_tag)
    github.add_label(config, issue.number, config.manual_work_tag)


def _run_tests(test_command: str, repo_path: Path) -> tuple[bool, str]:
    """Run the test command, return (passed, error_output)."""
    print(f"Running tests: {test_command}")
    result = subprocess.run(
        test_command,
        cwd=repo_path,
        shell=True,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode == 0:
        print("Tests passed.")
        return True, ""
    error_output = result.stdout[-6000:] + "\n" + result.stderr[-2000:]
    print("Tests failed.")
    return False, error_output
