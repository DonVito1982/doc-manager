"""Unit tests for the collector module."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

import pytest

from documentos.build.collector import (
    RECOGNIZED_SUFFIXES,
    SourceFile,
    _parse_frontmatter_md,
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


def _minimal_notebook(cells: list[dict], metadata: dict | None = None) -> str:
    metadata = metadata or {}
    return json.dumps(
        {"cells": cells, "metadata": metadata, "nbformat": 4, "nbformat_minor": 2}
    )


class TestSourceFile:
    """Tests for the SourceFile dataclass and its public methods."""

    # -- fields -----------------------------------------------------------

    def test_fields_exist(self):
        sf = SourceFile(path=Path("a.md"), format="md", frontmatter={})
        assert sf.path == Path("a.md")
        assert sf.format == "md"
        assert sf.frontmatter == {}

    def test_default_frontmatter_is_empty(self):
        sf = SourceFile(path=Path("a.md"), format="md")
        assert sf.frontmatter == {}

    # -- should_skip ------------------------------------------------------

    def test_should_skip_dot_prefix(self):
        assert SourceFile.should_skip(".hidden") is True

    def test_should_skip_underscore_prefix(self):
        assert SourceFile.should_skip("_draft") is True

    def test_should_skip_normal_name(self):
        assert SourceFile.should_skip("visible") is False

    # -- detect_format ----------------------------------------------------

    def test_detect_format_md(self):
        assert SourceFile.detect_format(Path("file.md")) == "md"

    def test_detect_format_md_j2(self):
        assert SourceFile.detect_format(Path("template.md.j2")) == "md.j2"

    def test_detect_format_ipynb(self):
        assert SourceFile.detect_format(Path("notebook.ipynb")) == "ipynb"

    def test_detect_format_adoc(self):
        assert SourceFile.detect_format(Path("document.adoc")) == "adoc"

    def test_detect_format_unrecognized(self):
        assert SourceFile.detect_format(Path("notes.txt")) is None

    def test_detect_format_no_extension(self):
        assert SourceFile.detect_format(Path("README")) is None

    # -- parse_frontmatter (md / md.j2) -----------------------------------

    def test_parse_frontmatter_md_with_metadata(self, tmp_path: Path):
        content = tmp_path / "content"
        content.mkdir()
        file = content / "doc.md"
        file.write_text("---\ntitle: Hello\nauthor: Alice\n---\n# Content")
        sf = SourceFile(path=Path("content/doc.md"), format="md")
        sf.parse_frontmatter(tmp_path)
        assert sf.frontmatter == {"title": "Hello", "author": "Alice"}

    def test_parse_frontmatter_md_without_metadata(self, tmp_path: Path):
        content = tmp_path / "content"
        content.mkdir()
        file = content / "doc.md"
        file.write_text("# Just content\nSome text")
        sf = SourceFile(path=Path("content/doc.md"), format="md")
        sf.parse_frontmatter(tmp_path)
        assert sf.frontmatter == {}

    def test_parse_frontmatter_md_empty_file(self, tmp_path: Path):
        content = tmp_path / "content"
        content.mkdir()
        file = content / "doc.md"
        file.write_text("")
        sf = SourceFile(path=Path("content/doc.md"), format="md")
        sf.parse_frontmatter(tmp_path)
        assert sf.frontmatter == {}

    def test_parse_frontmatter_md_j2(self, tmp_path: Path):
        content = tmp_path / "content"
        content.mkdir()
        file = content / "template.md.j2"
        file.write_text("---\ntitle: Jinja\n---\n{{ content }}")
        sf = SourceFile(path=Path("content/template.md.j2"), format="md.j2")
        sf.parse_frontmatter(tmp_path)
        assert sf.frontmatter == {"title": "Jinja"}

    # -- parse_frontmatter (ipynb) ----------------------------------------

    def test_parse_frontmatter_ipynb_title(self, tmp_path: Path):
        content = tmp_path / "content"
        content.mkdir()
        nb = _minimal_notebook(
            [{"cell_type": "markdown", "source": ["# Introduction"]}],
        )
        file = content / "notebook.ipynb"
        file.write_text(nb)
        sf = SourceFile(path=Path("content/notebook.ipynb"), format="ipynb")
        sf.parse_frontmatter(tmp_path)
        assert sf.frontmatter == {"title": "Introduction"}

    def test_parse_frontmatter_ipynb_multiline_title(self, tmp_path: Path):
        content = tmp_path / "content"
        content.mkdir()
        nb = _minimal_notebook(
            [{"cell_type": "markdown", "source": ["# ", "My Title"]}],
        )
        file = content / "notebook.ipynb"
        file.write_text(nb)
        sf = SourceFile(path=Path("content/notebook.ipynb"), format="ipynb")
        sf.parse_frontmatter(tmp_path)
        assert sf.frontmatter["title"] == "My Title"

    def test_parse_frontmatter_ipynb_author(self, tmp_path: Path):
        content = tmp_path / "content"
        content.mkdir()
        nb = _minimal_notebook(
            [{"cell_type": "markdown", "source": ["# Title"]}],
            metadata={"author": "Bob"},
        )
        file = content / "notebook.ipynb"
        file.write_text(nb)
        sf = SourceFile(path=Path("content/notebook.ipynb"), format="ipynb")
        sf.parse_frontmatter(tmp_path)
        assert sf.frontmatter == {"title": "Title", "author": "Bob"}

    def test_parse_frontmatter_ipynb_no_markdown(self, tmp_path: Path):
        content = tmp_path / "content"
        content.mkdir()
        nb = _minimal_notebook([{"cell_type": "code", "source": ["print(1)"]}])
        file = content / "notebook.ipynb"
        file.write_text(nb)
        sf = SourceFile(path=Path("content/notebook.ipynb"), format="ipynb")
        sf.parse_frontmatter(tmp_path)
        assert sf.frontmatter == {}

    def test_parse_frontmatter_ipynb_invalid_json(self, tmp_path: Path):
        content = tmp_path / "content"
        content.mkdir()
        file = content / "notebook.ipynb"
        file.write_text("not valid json")
        sf = SourceFile(path=Path("content/notebook.ipynb"), format="ipynb")
        sf.parse_frontmatter(tmp_path)
        assert sf.frontmatter == {}

    # -- parse_frontmatter (adoc) -----------------------------------------

    def test_parse_frontmatter_adoc(self, tmp_path: Path):
        content = tmp_path / "content"
        content.mkdir()
        file = content / "doc.adoc"
        file.write_text("= Title\nContent")
        sf = SourceFile(path=Path("content/doc.adoc"), format="adoc")
        sf.parse_frontmatter(tmp_path)
        assert sf.frontmatter == {}


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
        nb = json.dumps(
            {
                "cells": [{"cell_type": "markdown", "source": ["# Notebook Title"]}],
                "metadata": {"author": "Carlos"},
                "nbformat": 4,
                "nbformat_minor": 2,
            }
        )
        (content / "notebook.ipynb").write_text(nb)
        results = collect(project_config)
        assert len(results) == 1
        assert results[0].format == "ipynb"
        assert results[0].frontmatter == {
            "title": "Notebook Title",
            "author": "Carlos",
        }

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
            json.dumps(
                {
                    "cells": [{"cell_type": "markdown", "source": ["# Notebook"]}],
                    "metadata": {},
                    "nbformat": 4,
                    "nbformat_minor": 2,
                }
            )
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

    def test_collect_skips_index_md(
        self, project_config: ProjectConfig, tmp_path: Path
    ):
        """_index.md files are NOT collected as SourceFile."""
        content = tmp_path / "content"
        (content / "_index.md").write_text("---\ntitle: Root\n---")
        (content / "doc.md").write_text("# Doc")
        sub = content / "guias"
        sub.mkdir()
        (sub / "_index.md").write_text("---\ntitle: Guías\n---")
        (sub / "guia.md").write_text("# Guía")
        results = collect(project_config)
        assert len(results) == 2
        paths = {str(r.path) for r in results}
        assert "content/_index.md" not in paths
        assert "content/guias/_index.md" not in paths
        assert "content/doc.md" in paths
        assert "content/guias/guia.md" in paths

    def test_collect_skips_index_md_j2(
        self, project_config: ProjectConfig, tmp_path: Path
    ):
        """_index.md.j2 files are also NOT collected."""
        content = tmp_path / "content"
        (content / "_index.md.j2").write_text("---\ntitle: Root\n---")
        (content / "doc.md").write_text("# Doc")
        results = collect(project_config)
        assert len(results) == 1
        assert results[0].path == Path("content/doc.md")


# ---------------------------------------------------------------------------
# SourceFile.section property
# ---------------------------------------------------------------------------


class TestSectionProperty:
    """Tests for the SourceFile.section computed property."""

    def test_root_section(self):
        """Files directly in content/ have section '' (root)."""
        sf = SourceFile(path=Path("content/index.md"), format="md")
        assert sf.section == ""

    def test_first_level_subdir_section(self):
        """Files in content/<subdir>/ have section <subdir>."""
        sf = SourceFile(path=Path("content/guias/instalacion.md"), format="md")
        assert sf.section == "guias"

    def test_deeply_nested_section(self):
        """Deeply nested files still have first-level section."""
        sf = SourceFile(path=Path("content/guias/sub/deep.md"), format="md")
        assert sf.section == "guias"

    def test_no_content_prefix(self):
        """Files without content prefix return ''."""
        sf = SourceFile(path=Path("other/doc.md"), format="md")
        assert sf.section == ""

    def test_single_component_path(self):
        """Single-component path returns ''."""
        sf = SourceFile(path=Path("index.md"), format="md")
        assert sf.section == ""


class TestRecognizedSuffixes:
    """Ensure the constant maps correctly."""

    def test_all_extensions_present(self):
        assert RECOGNIZED_SUFFIXES == {
            ".md.j2": "md.j2",
            ".md": "md",
            ".ipynb": "ipynb",
            ".adoc": "adoc",
        }


# ---------------------------------------------------------------------------
# Edge-case coverage tests
# ---------------------------------------------------------------------------


class TestParseFrontmatterEdgeCases:
    """Cover internal branches of _parse_frontmatter_md and _parse_frontmatter_ipynb."""

    def test_parse_frontmatter_md_exception_triggers_empty_dict(
        self, tmp_path: Path
    ) -> None:
        """Passing a directory (not a file) to _parse_frontmatter_md triggers
        the broad except and returns {}."""
        dir_path = tmp_path / "content"
        dir_path.mkdir()
        result = _parse_frontmatter_md(dir_path)
        assert result == {}

    def test_parse_frontmatter_ipynb_string_source(self, tmp_path: Path) -> None:
        """Notebook with source as a plain string (not a list of strings) still
        parses the title."""
        content = tmp_path / "content"
        content.mkdir()
        nb = _minimal_notebook(
            [{"cell_type": "markdown", "source": "# String Title"}],
        )
        # Override _minimal_notebook so that source is a string
        nb_data = json.loads(nb)
        nb_data["cells"][0]["source"] = "# String Title"
        file = content / "nb.ipynb"
        file.write_text(json.dumps(nb_data))
        sf = SourceFile(path=Path("content/nb.ipynb"), format="ipynb")
        sf.parse_frontmatter(tmp_path)
        assert sf.frontmatter["title"] == "String Title"

    def test_parse_frontmatter_ipynb_no_h1_heading(self, tmp_path: Path) -> None:
        """Markdown cell without a '# ' prefix: title falls back to the first
        line, stripping leading '#' characters."""
        content = tmp_path / "content"
        content.mkdir()
        nb = _minimal_notebook(
            [{"cell_type": "markdown", "source": ["## Subtitle\n", "More text\n"]}],
        )
        file = content / "nb.ipynb"
        file.write_text(nb)
        sf = SourceFile(path=Path("content/nb.ipynb"), format="ipynb")
        sf.parse_frontmatter(tmp_path)
        assert sf.frontmatter["title"] == "Subtitle"
