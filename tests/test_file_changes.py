import json

import pytest

from gertrudes.file_changes import parse_llm_response, apply_changes


def test_parse_clean_json():
    raw = json.dumps({"src/app.py": "print('hello')"})
    result = parse_llm_response(raw)
    assert result == {"src/app.py": "print('hello')"}


def test_parse_json_in_code_fence():
    raw = '```json\n{"src/app.py": "print(1)"}\n```'
    result = parse_llm_response(raw)
    assert result == {"src/app.py": "print(1)"}


def test_parse_json_in_plain_fence():
    raw = '```\n{"src/app.py": "code"}\n```'
    result = parse_llm_response(raw)
    assert result == {"src/app.py": "code"}


def test_parse_with_preamble_and_fence():
    raw = 'Here are the changes:\n\n```json\n{"a.py": "x"}\n```\n\nDone!'
    result = parse_llm_response(raw)
    assert result == {"a.py": "x"}


def test_parse_invalid_json_raises():
    with pytest.raises(ValueError, match="Could not parse"):
        parse_llm_response("this is not json at all")


def test_apply_changes_writes_files(tmp_path):
    changes = {
        "src/app.py": "print('hello')",
        "src/utils/helper.py": "def help(): pass",
    }
    written = apply_changes(tmp_path, changes)
    assert set(written) == {"src/app.py", "src/utils/helper.py"}
    assert (tmp_path / "src/app.py").read_text() == "print('hello')"
    assert (tmp_path / "src/utils/helper.py").read_text() == "def help(): pass"


def test_apply_changes_creates_directories(tmp_path):
    changes = {"deep/nested/dir/file.py": "content"}
    apply_changes(tmp_path, changes)
    assert (tmp_path / "deep/nested/dir/file.py").exists()


def test_parse_json_list_raises():
    """LLM returns a JSON list instead of a dict."""
    with pytest.raises(ValueError, match="Could not parse"):
        parse_llm_response('[{"file": "src/app.py"}]')


def test_parse_empty_string_raises():
    with pytest.raises(ValueError, match="Could not parse"):
        parse_llm_response("")


def test_parse_json_list_in_fence_raises():
    raw = '```json\n["not", "a", "dict"]\n```'
    with pytest.raises(ValueError, match="Could not parse"):
        parse_llm_response(raw)


def test_parse_whitespace_only_raises():
    with pytest.raises(ValueError, match="Could not parse"):
        parse_llm_response("   \n\n  ")
