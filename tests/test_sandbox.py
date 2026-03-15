"""Tests for path traversal protection."""

from __future__ import annotations

import pytest

from gertrudes.sandbox import safe_resolve


def test_safe_resolve_normal_path(tmp_path):
    result = safe_resolve(tmp_path, "src/app.py")
    assert result == (tmp_path / "src/app.py").resolve()


def test_safe_resolve_nested_path(tmp_path):
    result = safe_resolve(tmp_path, "a/b/c/d.py")
    assert result == (tmp_path / "a/b/c/d.py").resolve()


def test_safe_resolve_root_file(tmp_path):
    result = safe_resolve(tmp_path, "README.md")
    assert result == (tmp_path / "README.md").resolve()


def test_safe_resolve_parent_traversal_raises(tmp_path):
    with pytest.raises(ValueError, match="escapes the repository root"):
        safe_resolve(tmp_path, "../escape.py")


def test_safe_resolve_deep_traversal_raises(tmp_path):
    with pytest.raises(ValueError, match="escapes the repository root"):
        safe_resolve(tmp_path, "src/../../outside.py")


def test_safe_resolve_absolute_path_raises(tmp_path):
    with pytest.raises(ValueError, match="escapes the repository root"):
        safe_resolve(tmp_path, "/etc/passwd")


def test_safe_resolve_etc_passwd_via_traversal_raises(tmp_path):
    with pytest.raises(ValueError, match="escapes the repository root"):
        safe_resolve(tmp_path, "../../../etc/passwd")
