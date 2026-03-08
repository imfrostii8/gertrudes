# gertrudes

Gertrudes picks up GitHub issues tagged with a configurable label and automatically implements them using an LLM, then opens a pull request. It's optimized to work with Claude's code plan mode as the issue creator, which naturally generates the structured implementation plans gertrudes expects.

## How it works

1. Fetches open issues with the `ready-to-implement` label (configurable)
2. Parses a step-by-step plan from the issue body
3. Clones the repo, creates a branch (`gertrudes/issue-<number>`)
4. Implements each step using the configured LLM
5. Optionally runs tests and retries fixes on failure
6. Pushes the branch and opens a PR (draft if partial or tests fail)

## Requirements

- Python 3.10+
- A GitHub personal access token with `repo` scope
- An API key for your chosen LLM (e.g. `ANTHROPIC_API_KEY`)

## Installation

```bash
pip install gertrudes
```

Or from source:

```bash
git clone https://github.com/imfrostii8/gertrudes.git
cd gertrudes
pip install .
```

## Configuration

Copy the example config and fill it in:

```bash
cp config.example.yaml gertrudes.yaml
```

```yaml
# Required
repo: "owner/repo"

# LLM — any litellm-compatible model string
llm_model: "anthropic/claude-sonnet-4-20250514"

# Labels
issue_tag: "ready-to-implement"
implementing_tag: "implementing"
done_tag: "implemented"
pr_label: "automated-pr"

# Optional
base_branch: "main"
test_command: null     # e.g. "pytest", "npm test"
max_fix_retries: 2
workdir: null          # null = use a temp directory
```

Set your tokens as environment variables (or in a `.env` file):

```bash
export GITHUB_TOKEN=ghp_...
export ANTHROPIC_API_KEY=sk-ant-...  # or whichever LLM you use
```

## Usage

```bash
gertrudes
# or with a custom config path:
gertrudes --config path/to/gertrudes.yaml
```

Gertrudes will pick one eligible issue at random, implement it, and open a PR.

## Issue format

Issues should contain a markdown plan with `##` headings as steps. Each step can mention file paths that the LLM will read before implementing.

```markdown
## Add input validation

Validate the `email` field in `src/auth/signup.py` before saving.

## Add tests

Add tests in `tests/test_auth.py` covering valid and invalid emails.
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT
