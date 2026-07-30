"""Unit tests for the collector module."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

import pytest

from documentos.build.collector import (
    RECOGNIZED_SUFFIXES,
    SourceFile,
    _detect_format,
    _parse_frontmatter_ipynb,
    _parse_frontmatter_md,
    _should_skip,
    collect,
)
from documentos.config import ProjectConfig


@pytest.fixture
def project_config(tmp_path: Path) -> ProjectConfig:
    """Create a minimal ProjectConfig rooted at *tmp_path*."""
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    return ProjectConfig(root=tmp_path)


@pytest.fixture
def populate(project_config: ProjectConfig) -> Generator[ProjectConfig, None, None]:
    """Return a config whose content/ dir can be populated by tests.

    Usage in test::

        def test_foo(populate, tmp_path):
            (tmp_path / "content" / "foo.md").write_text("...")
            results = collect(populate)
    """
    yield project_config


class TestSourceFile:
    """Tests for the SourceFile dataclass."""

    def test_fields_exist(self):
        sf = SourceFile(path=Path("a.md"), format="md", frontmatter={})
        assert sf.path == Path("a.md")
        assert sf.format == "md"
        assert sf.frontmatter == {}

    def test_default_frontmatter_is_empty(self):
        sf = SourceFile(path=Path("a.md"), format="md", frontmatter={})
        assert sf.frontmatter == {}


class TestDetectFormat:
    """Tests for the _detect_format helper."""

    def test_md_extension(self):
        assert _detect_format(Path("file.md")) == "md"

    def test_md_j2_double_extension(self):
        assert _detect_format(Path("template.md.j2")) == "md.j2"

    def test_ipynb_extension(self):
        assert _detect_format(Path("notebook.ipynb")) == "ipynb"

    def test_adoc_extension(self):
        assert _detect_format(Path("document.adoc")) == "adoc"

    def test_unrecognized_extension(self):
        assert _detect_format(Path("notes.txt")) is None
        assert _detect_format(Path("doc.rst")) is None

    def test_no_extension(self):
        assert _detect_format(Path("README")) is None


class TestShouldSkip:
    """Tests for the _should_skip helper."""

    def test_dot_prefix(self):
        assert _should_skip(".hidden") is True

    def test_underscore_prefix(self):
        assert _should_skip("_draft") is True

    def test_normal_name(self):
        assert _should_skip("visible") is False


class TestParseFrontmatterMd:
    """Tests for _parse_frontmatter_md."""

    def test_with_frontmatter(self, tmp_path: Path):
        file = tmp_path / "doc.md"
        file.write_text("---\ntitle: Hello\nauthor: Alice\n---\n# Content")
        result = _parse_frontmatter_md(file)
        assert result == {"title": "Hello", "author": "Alice"}

    def test_without_frontmatter(self, tmp_path: Path):
        file = tmp_path / "doc.md"
        file.write_text("# Just content\nSome text")
        result = _parse_frontmatter_md(file)
        assert result == {}

    def test_empty_file(self, tmp_path: Path):
        file = tmp_path / "doc.md"
        file.write_text("")
        result = _parse_frontmatter_md(file)
        assert result == {}


class TestParseFrontmatterIpynb:
    """Tests for _parse_frontmatter_ipynb."""

    def _minimal_notebook(self, cells: list[dict], metadata: dict | None = None) -> str:
        metadata = metadata or {}
        return json.dumps(
            {"cells": cells, "metadata": metadata, "nbformat": 4, "nbformat_minor": 2}
        )

    def test_title_from_first_markdown_cell(self, tmp_path: Path):
        nb = self._minimal_notebook(
            cells=[
                {"cell_type": "markdown", "source": ["# Introduction"]},
                {"cell_type": "code", "source": ["print(1)"]},
            ]
        )
        file = tmp_path / "notebook.ipynb"
        file.write_text(nb)
        result = _parse_frontmatter_ipynb(file)
        assert result["title"] == "Introduction"

    def test_title_from_multiline_source(self, tmp_path: Path):
        nb = self._minimal_notebook(
            cells=[
                {"cell_type": "markdown", "source": ["# ", "My Title"]},
            ]
        )
        file = tmp_path / "notebook.ipynb"
        file.write_text(nb)
        result = _parse_frontmatter_ipynb(file)
        assert result["title"] == "My Title"

    def test_author_from_metadata(self, tmp_path: Path):
        nb = self._minimal_notebook(
            cells=[{"cell_type": "markdown", "source": ["# Title"]}],
            metadata={"author": "Bob"},
        )
        file = tmp_path / "notebook.ipynb"
        file.write_text(nb)
        result = _parse_frontmatter_ipynb(file)
        assert result["author"] == "Bob"
        assert result["title"] == "Title"

    def test_no_markdown_cells(self, tmp_path: Path):
        nb = self._minimal_notebook(
            cells=[{"cell_type": "code", "source": ["print(1)"]}],
        )
        file = tmp_path / "notebook.ipynb"
        file.write_text(nb)
        result = _parse_frontmatter_ipynb(file)
        assert result == {}

    def test_no_author_in_metadata(self, tmp_path: Path):
        nb = self._minimal_notebook(
            cells=[{"cell_type": "markdown", "source": ["# Title"]}],
        )
        file = tmp_path / "notebook.ipynb"
        file.write_text(nb)
        result = _parse_frontmatter_ipynb(file)
        assert "author" not in result
        assert result["title"] == "Title"

    def test_invalid_json(self, tmp_path: Path):
        file = tmp_path / "notebook.ipynb"
        file.write_text("not valid json")
        result = _parse_frontmatter_ipynb(file)
        assert result == {}


class TestCollect:
    """Integration-style tests for the collect() function."""

    def test_empty_content_directory(
        self, project_config: ProjectConfig, tmp_path: Path
    ):
        results = collect(project_config)
        assert results == []

    def test_missing_content_directory(self, tmp_path: Path):
        config = ProjectConfig(root=tmp_path)
        results = collect(config)
        assert results == []

    def test_collects_md_with_frontmatter(
        self, project_config: ProjectConfig, tmp_path: Path
    ):
        content = tmp_path / "content"
        (content / "intro.md").write_text("---\ntitle: Intro\n---\n# Intro")
        results = collect(project_config)
        assert len(results) == 1
        assert results[0].path == Path("content/intro.md")
        assert results[0].format == "md"
        assert results[0].frontmatter == {"title": "Intro"}

    def test_collects_md_without_frontmatter(
        self, project_config: ProjectConfig, tmp_path: Path
    ):
        content = tmp_path / "content"
        (content / "plain.md").write_text("# No frontmatter here")
        results = collect(project_config)
        assert len(results) == 1
        assert results[0].format == "md"
        assert results[0].frontmatter == {}

    def test_collects_md_j2(self, project_config: ProjectConfig, tmp_path: Path):
        content = tmp_path / "content"
        (content / "template.md.j2").write_text("---\ntitle: Jinja\n---\n{{ content }}")
        results = collect(project_config)
        assert len(results) == 1
        assert results[0].path == Path("content/template.md.j2")
        assert results[0].format == "md.j2"
        assert results[0].frontmatter == {"title": "Jinja"}

    def test_collects_ipynb(self, project_config: ProjectConfig, tmp_path: Path):
        content = tmp_path / "content"
        nb = json.dumps({
            "cells": [{"cell_type": "markdown", "source": ["# Notebook Title"]}],
            "metadata": {"author": "Carlos"},
            "nbformat": 4,
            "nbformat_minor": 2,
        })
        (content / "notebook.ipynb").write_text(nb)
        results = collect(project_config)
        assert len(results) == 1
        assert results[0].format == "ipynb"
        assert results[0].frontmatter == {"title": "Notebook Title", "author": "Carlos"}

    def test_collects_adoc(self, project_config: ProjectConfig, tmp_path: Path):
        content = tmp_path / "content"
        (content / "doc.adoc").write_text("= Title\nContent")
        results = collect(project_config)
        assert len(results) == 1
        assert results[0].format == "adoc"
        assert results[0].frontmatter == {}

    def test_ignores_hidden_files(self, project_config: ProjectConfig, tmp_path: Path):
        content = tmp_path / "content"
        (content / ".hidden.md").write_text("---\ntitle: Hidden\n---\n# nope")
        (content / "_draft.md").write_text("# Draft")
        (content / "visible.md").write_text("# Visible")
        results = collect(project_config)
        assert len(results) == 1
        assert results[0].path == Path("content/visible.md")

    def test_ignores_hidden_directories(
        self, project_config: ProjectConfig, tmp_path: Path
    ):
        content = tmp_path / "content"
        hidden_dir = content / "_drafts"
        hidden_dir.mkdir()
        (hidden_dir / "secret.md").write_text("# Secret")
        dot_dir = content / ".private"
        dot_dir.mkdir()
        (dot_dir / "private.md").write_text("# Private")
        (content / "public.md").write_text("# Public")
        results = collect(project_config)
        assert len(results) == 1
        assert results[0].path == Path("content/public.md")

    def test_ignores_unrecognized_extensions(
        self, project_config: ProjectConfig, tmp_path: Path
    ):
        content = tmp_path / "content"
        (content / "notes.txt").write_text("Plain text")
        (content / "doc.rst").write_text("reStructuredText")
        (content / "readme.md").write_text("# Readme")
        results = collect(project_config)
        assert len(results) == 1
        assert results[0].format == "md"

    def test_sorted_alphabetically(self, project_config: ProjectConfig, tmp_path: Path):
        content = tmp_path / "content"
        (content / "zebra.md").write_text("# Z")
        (content / "alpha.md").write_text("# A")
        (content / "mid.md").write_text("# M")
        results = collect(project_config)
        paths = [r.path for r in results]
        assert paths == sorted(paths)

    def test_multiple_formats(self, project_config: ProjectConfig, tmp_path: Path):
        content = tmp_path / "content"
        (content / "a.md").write_text("---\ntitle: MD\n---\n# a")
        (content / "b.adoc").write_text("= AsciiDoc")
        (content / "c.ipynb").write_text(
            json.dumps({
                "cells": [{"cell_type": "markdown", "source": ["# Notebook"]}],
                "metadata": {},
                "nbformat": 4,
                "nbformat_minor": 2,
            })
        )
        (content / "d.md.j2").write_text("---\ntitle: Template\n---\n{{ x }}")
        results = collect(project_config)
        assert len(results) == 4
        formats = {r.format for r in results}
        assert formats == {"md", "adoc", "ipynb", "md.j2"}

    def test_nested_directories(self, project_config: ProjectConfig, tmp_path: Path):
        content = tmp_path / "content"
        sub = content / "subdir"
        sub.mkdir()
        (content / "root.md").write_text("# Root")
        (sub / "nested.md").write_text("# Nested")
        results = collect(project_config)
        paths = {r.path for r in results}
        assert len(results) == 2
        assert Path("content/root.md") in paths
        assert Path("content/subdir/nested.md") in paths


class TestRecognizedSuffixes:
    """Ensure the constant maps correctly."""

    def test_all_extensions_present(self):
        assert RECOGNIZED_SUFFIXES == {
            ".md.j2": "md.j2",
            ".md": "md",
            ".ipynb": "ipynb",
            ".adoc": "adoc",
        }
