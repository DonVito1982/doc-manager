"""Unit tests for the indexer module."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from documentos.build.collector import SourceFile
from documentos.build.indexer import generate_index
from documentos.config import ProjectConfig


@pytest.fixture
def sample_sources() -> list[SourceFile]:
    """Create sample SourceFile objects for testing."""
    return [
        SourceFile(
            path=Path("content/guias/instalacion.md"),
            format="md",
            frontmatter={"title": "Instalacion"},
        ),
        SourceFile(
            path=Path("content/index.md"),
            format="md",
            frontmatter={"title": "Bienvenido"},
        ),
        SourceFile(
            path=Path("content/api/referencia.md"),
            format="md",
            frontmatter={"title": "Referencia API"},
        ),
    ]


@pytest.fixture
def project_config(tmp_path: Path) -> ProjectConfig:
    """Create a ProjectConfig with necessary directories."""
    (tmp_path / "content").mkdir(exist_ok=True)
    (tmp_path / "output" / "html").mkdir(parents=True, exist_ok=True)
    return ProjectConfig(root=tmp_path)


# ---------------------------------------------------------------------------
# Flat index (no .index.yml)
# ---------------------------------------------------------------------------


class TestFlatIndex:
    def test_generates_index_html(self, sample_sources, project_config):
        """generate_index creates output/html/index.html."""
        path = generate_index(sample_sources, project_config)
        assert path == project_config.root / "output" / "html" / "index.html"
        assert path.is_file()

    def test_index_contains_all_titles(self, sample_sources, project_config):
        """All document titles appear in the index."""
        path = generate_index(sample_sources, project_config)
        html = path.read_text(encoding="utf-8")
        assert "Bienvenido" in html
        assert "Instalacion" in html
        assert "Referencia API" in html

    def test_alphabetical_order_by_title(self, sample_sources, project_config):
        """Documents are sorted alphabetically by title (no .index.yml)."""
        path = generate_index(sample_sources, project_config)
        html = path.read_text(encoding="utf-8")
        pos_bienvenido = html.index("Bienvenido")
        pos_instalacion = html.index("Instalacion")
        pos_referencia = html.index("Referencia API")
        assert pos_bienvenido < pos_instalacion < pos_referencia

    def test_links_are_relative(self, sample_sources, project_config):
        """Links in index are relative to index.html."""
        path = generate_index(sample_sources, project_config)
        html = path.read_text(encoding="utf-8")
        assert 'href="guias/instalacion.html"' in html
        assert 'href="api/referencia.html"' in html
        assert 'href="index.html"' in html

    def test_empty_sources(self, project_config):
        """Index with no documents shows 'No hay documentos'."""
        path = generate_index([], project_config)
        html = path.read_text(encoding="utf-8")
        assert "No hay documentos" in html

    def test_fallback_to_filename_when_no_title(self, project_config):
        """Documents without frontmatter title use filename stem."""
        source = SourceFile(
            path=Path("content/doc.md"),
            format="md",
            frontmatter={},
        )
        path = generate_index([source], project_config)
        html = path.read_text(encoding="utf-8")
        assert ">doc<" in html

    def test_project_title_in_index(self, sample_sources, project_config):
        """The project title appears in the index h1."""
        project_config.project.title = "Mi Proyecto"
        path = generate_index(sample_sources, project_config)
        html = path.read_text(encoding="utf-8")
        assert "<h1>Mi Proyecto</h1>" in html

    def test_html_escapes_special_chars_in_title(self, project_config):
        """HTML special characters in titles are escaped."""
        source = SourceFile(
            path=Path("content/test.md"),
            format="md",
            frontmatter={"title": "Test <script>alert(1)</script>"},
        )
        path = generate_index([source], project_config)
        html = path.read_text(encoding="utf-8")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


# ---------------------------------------------------------------------------
# Sectioned index (with .index.yml)
# ---------------------------------------------------------------------------


class TestSectionedIndex:
    def test_sections_from_index_yml(self, sample_sources, project_config):
        """.index.yml sections are rendered with headings."""
        index_yml = project_config.root / "content" / ".index.yml"
        index_yml.write_text(
            yaml.dump(
                {
                    "sections": [
                        {
                            "title": "General",
                            "files": ["content/index.md"],
                        },
                        {
                            "title": "Referencias",
                            "files": [
                                "content/guias/instalacion.md",
                                "content/api/referencia.md",
                            ],
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

        path = generate_index(sample_sources, project_config)
        html = path.read_text(encoding="utf-8")
        assert "<h2>General</h2>" in html
        assert "<h2>Referencias</h2>" in html

    def test_section_respects_explicit_order(self, sample_sources, project_config):
        """YML ordering is respected, not alphabetical."""
        index_yml = project_config.root / "content" / ".index.yml"
        index_yml.write_text(
            yaml.dump(
                {
                    "sections": [
                        {
                            "title": "Docs",
                            "files": [
                                "content/api/referencia.md",
                                "content/index.md",
                            ],
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

        path = generate_index(sample_sources, project_config)
        html = path.read_text(encoding="utf-8")
        pos_ref = html.index("Referencia API")
        pos_index = html.index("Bienvenido")
        assert pos_ref < pos_index

    def test_files_not_in_sources_are_skipped(self, sample_sources, project_config):
        """Files listed in .index.yml but not in sources are silently skipped."""
        index_yml = project_config.root / "content" / ".index.yml"
        index_yml.write_text(
            yaml.dump(
                {
                    "sections": [
                        {
                            "title": "Docs",
                            "files": [
                                "content/index.md",
                                "content/nonexistent.md",
                            ],
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

        path = generate_index(sample_sources, project_config)
        html = path.read_text(encoding="utf-8")
        assert "Bienvenido" in html
        assert "nonexistent" not in html

    def test_empty_sections_are_filtered(self, sample_sources, project_config):
        """Sections with no title or no files are filtered out."""
        index_yml = project_config.root / "content" / ".index.yml"
        index_yml.write_text(
            yaml.dump(
                {
                    "sections": [
                        {"title": "", "files": ["content/index.md"]},
                        {"title": "Valid", "files": ["content/index.md"]},
                        {"title": "NoFiles", "files": []},
                    ]
                }
            ),
            encoding="utf-8",
        )

        path = generate_index(sample_sources, project_config)
        html = path.read_text(encoding="utf-8")
        sections = html.count("<h2>")
        assert sections == 1
        assert "<h2>Valid</h2>" in html

    def test_invalid_yaml_falls_back_to_flat(self, sample_sources, project_config):
        """Invalid YAML in .index.yml falls back to flat alphabetical index."""
        index_yml = project_config.root / "content" / ".index.yml"
        index_yml.write_text(":invalid yaml: [", encoding="utf-8")

        path = generate_index(sample_sources, project_config)
        html = path.read_text(encoding="utf-8")
        # Should be flat (alphabetical), no sections
        assert "<h2>" not in html

    def test_missing_index_yml_falls_back_to_flat(self, sample_sources, project_config):
        """When .index.yml does not exist, flat index is generated."""
        path = generate_index(sample_sources, project_config)
        html = path.read_text(encoding="utf-8")
        assert "<h2>" not in html
        assert "Bienvenido" in html
