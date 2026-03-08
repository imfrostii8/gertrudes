from gertrudes.planner import parse_plan


def test_extracts_file_paths_from_backticks():
    body = """
## Plan
- Modify `src/utils.py` to add helper
- Create `src/new_module.py`
- Update `lib/config.ts`
"""
    plan = parse_plan(body)
    assert "src/utils.py" in plan.mentioned_files
    assert "src/new_module.py" in plan.mentioned_files
    assert "lib/config.ts" in plan.mentioned_files


def test_extracts_file_paths_without_backticks():
    body = """
## Files to change
- src/app.py
- src/routes/auth.py
"""
    plan = parse_plan(body)
    assert "src/app.py" in plan.mentioned_files
    assert "src/routes/auth.py" in plan.mentioned_files


def test_ignores_non_code_files():
    body = """
See README.md and docs/guide.txt for details.
Modify `src/main.py` and check screenshot.png.
"""
    plan = parse_plan(body)
    assert "src/main.py" in plan.mentioned_files
    assert "README.md" not in plan.mentioned_files
    assert "screenshot.png" not in plan.mentioned_files
    assert "docs/guide.txt" not in plan.mentioned_files


def test_deduplicates_paths():
    body = """
Update `src/app.py` in step 1.
Then modify `src/app.py` again in step 2.
"""
    plan = parse_plan(body)
    assert plan.mentioned_files.count("src/app.py") == 1


def test_preserves_raw_markdown():
    body = "## My plan\nDo stuff"
    plan = parse_plan(body)
    assert plan.raw_markdown == body


def test_empty_body():
    plan = parse_plan("")
    assert plan.mentioned_files == []
    assert plan.raw_markdown == ""


# Step splitting tests

def test_splits_by_headers():
    body = """## Step 1: Add utils
Create `src/utils.py` with helpers.

## Step 2: Update app
Modify `src/app.py` to use utils.

## Step 3: Add tests
Create `tests/test_utils.py`.
"""
    plan = parse_plan(body)
    assert len(plan.steps) == 3
    assert plan.steps[0].title == "Step 1: Add utils"
    assert plan.steps[1].title == "Step 2: Update app"
    assert plan.steps[2].title == "Step 3: Add tests"


def test_step_has_mentioned_files():
    body = """## Add config
Create `src/config.py` with defaults.

## Update main
Modify `src/main.py` to load config.
"""
    plan = parse_plan(body)
    assert "src/config.py" in plan.steps[0].mentioned_files
    assert "src/main.py" in plan.steps[1].mentioned_files
    # Each step only has its own files
    assert "src/main.py" not in plan.steps[0].mentioned_files


def test_no_headers_single_step():
    body = "Just do stuff to `src/app.py` and `src/utils.py`."
    plan = parse_plan(body)
    assert len(plan.steps) == 1
    assert plan.steps[0].title == "Full plan"
    assert "src/app.py" in plan.steps[0].mentioned_files


def test_h3_headers_also_split():
    body = """### First thing
Change `src/a.py`.

### Second thing
Change `src/b.py`.
"""
    plan = parse_plan(body)
    assert len(plan.steps) == 2
    assert plan.steps[0].title == "First thing"


def test_empty_sections_skipped():
    body = """## Setup

## Implementation
Modify `src/app.py`.

## Cleanup
"""
    plan = parse_plan(body)
    # Only "Implementation" has content
    assert len(plan.steps) == 1
    assert plan.steps[0].title == "Implementation"


def test_step_body_content():
    body = """## Do the thing
This is the body.
It has multiple lines.
And mentions `src/foo.py`.
"""
    plan = parse_plan(body)
    assert "This is the body." in plan.steps[0].body
    assert "multiple lines" in plan.steps[0].body
