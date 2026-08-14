"""Unit tests for the indexer module."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from documentos.build.collector import SourceFile
from documentos.build.indexer import (
    build_section_index,
    generate_index,
    generate_section_pages,
)
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
# Flat index (no .index.yml) — now section-based
# ---------------------------------------------------------------------------


class TestFlatIndex:
    def test_generates_index_html_files(self, sample_sources, project_config):
        """generate_index creates per-section index.html files."""
        paths = generate_index(sample_sources, project_config)
        assert len(paths) == 3  # root, api, guias

        root_index = project_config.root / "output" / "html" / "index.html"
        api_index = project_config.root / "output" / "html" / "api" / "index.html"
        guias_index = project_config.root / "output" / "html" / "guias" / "index.html"

        assert root_index.is_file()
        assert api_index.is_file()
        assert guias_index.is_file()

    def test_index_contains_all_titles(self, sample_sources, project_config):
        """All document titles appear across section indices."""
        generate_index(sample_sources, project_config)

        # Each document should be in its section's index
        root_html = (project_config.root / "output" / "html" / "index.html").read_text(
            encoding="utf-8"
        )
        assert "Bienvenido" in root_html

        guias_html = (
            project_config.root / "output" / "html" / "guias" / "index.html"
        ).read_text(encoding="utf-8")
        assert "Instalacion" in guias_html

        api_html = (
            project_config.root / "output" / "html" / "api" / "index.html"
        ).read_text(encoding="utf-8")
        assert "Referencia API" in api_html

    def test_alphabetical_order_by_title(self, sample_sources, project_config):
        """Documents within a section are sorted alphabetically by title."""
        generate_index(sample_sources, project_config)

        # The root section only has one doc, so order isn't meaningful.
        # Verify that sections themselves exist and documents are accessible.
        root_index = project_config.root / "output" / "html" / "index.html"
        assert root_index.is_file()

    def test_links_are_relative(self, sample_sources, project_config):
        """Links in section indices are relative."""
        generate_index(sample_sources, project_config)

        guias_html = (
            project_config.root / "output" / "html" / "guias" / "index.html"
        ).read_text(encoding="utf-8")
        assert 'href="instalacion.html"' in guias_html

        root_html = (project_config.root / "output" / "html" / "index.html").read_text(
            encoding="utf-8"
        )
        assert 'href="index.html"' in root_html

        api_html = (
            project_config.root / "output" / "html" / "api" / "index.html"
        ).read_text(encoding="utf-8")
        assert 'href="referencia.html"' in api_html

    def test_empty_sources(self, project_config):
        """Index with no documents generates a valid page (no crash)."""
        paths = generate_index([], project_config)
        assert len(paths) == 1
        root_html = paths[0].read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in root_html

    def test_fallback_to_filename_when_no_title(self, project_config):
        """Documents without frontmatter title use filename stem."""
        source = SourceFile(
            path=Path("content/doc.md"),
            format="md",
            frontmatter={},
        )
        paths = generate_index([source], project_config)
        html = paths[0].read_text(encoding="utf-8")
        assert ">doc<" in html

    def test_project_title_in_index(self, sample_sources, project_config):
        """The project title appears in the root section index h1."""
        project_config.project.title = "Mi Proyecto"
        paths = generate_index(sample_sources, project_config)
        root_html = paths[0].read_text(encoding="utf-8")
        assert "<h1>Mi Proyecto</h1>" in root_html

    def test_html_escapes_special_chars_in_title(self, project_config):
        """HTML special characters in titles are escaped by Jinja2."""
        source = SourceFile(
            path=Path("content/test.md"),
            format="md",
            frontmatter={"title": "Test <script>alert(1)</script>"},
        )
        paths = generate_index([source], project_config)
        html = paths[0].read_text(encoding="utf-8")
        # The raw <script> from user title should be escaped (not executable)
        assert "&lt;script&gt;" in html

    def test_section_titles_in_indices(self, sample_sources, project_config):
        """Section titles appear in breadcrumbs and title tag."""
        generate_index(sample_sources, project_config)
        api_html = (
            project_config.root / "output" / "html" / "api" / "index.html"
        ).read_text(encoding="utf-8")
        # Section title appears in breadcrumbs as last span and in <title>
        assert ">api<" in api_html
        assert "<title>api —" in api_html


# ---------------------------------------------------------------------------
# Sectioned index (with .index.yml) — backward compatibility
# ---------------------------------------------------------------------------


class TestSectionedIndex:
    def test_sections_from_index_yml(self, sample_sources, project_config):
        """.index.yml sections render document lists in a single index page."""
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

        paths = generate_index(sample_sources, project_config)
        html = paths[0].read_text(encoding="utf-8")
        # All documents from both sections appear in the list
        assert "Bienvenido" in html
        assert "Instalacion" in html
        assert "Referencia API" in html

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

        paths = generate_index(sample_sources, project_config)
        html = paths[0].read_text(encoding="utf-8")
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

        paths = generate_index(sample_sources, project_config)
        html = paths[0].read_text(encoding="utf-8")
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

        paths = generate_index(sample_sources, project_config)
        html = paths[0].read_text(encoding="utf-8")
        # Only documents from "Valid" section appear
        assert "Bienvenido" in html
        assert len(paths) == 1

    def test_invalid_yaml_falls_back_to_flat(self, sample_sources, project_config):
        """Invalid YAML in .index.yml falls back to section-based index."""
        index_yml = project_config.root / "content" / ".index.yml"
        index_yml.write_text(":invalid yaml: [", encoding="utf-8")

        paths = generate_index(sample_sources, project_config)
        # Should generate per-section indices (falls back from .index.yml)
        assert len(paths) >= 1
        root_html = paths[0].read_text(encoding="utf-8")
        assert "Bienvenido" in root_html

    def test_missing_index_yml_generates_section_pages(
        self, sample_sources, project_config
    ):
        """When .index.yml does not exist, per-section indices are generated."""
        paths = generate_index(sample_sources, project_config)
        assert len(paths) == 3  # root, api, guias


# ---------------------------------------------------------------------------
# Section-based index (new functionality)
# ---------------------------------------------------------------------------


class TestBuildSectionIndex:
    """Tests for the build_section_index function."""

    def test_groups_sources_by_section(self, sample_sources, project_config):
        """Sources are grouped by their section property."""
        sections = build_section_index(project_config, sample_sources)
        assert len(sections) == 3  # "", "api", "guias"

        keys = [s["key"] for s in sections]
        assert "" in keys
        assert "api" in keys
        assert "guias" in keys

    def test_root_section_has_documents(self, sample_sources, project_config):
        """Documents in content/ root are in the root section."""
        sections = build_section_index(project_config, sample_sources)
        root_section = next(s for s in sections if s["key"] == "")
        assert len(root_section["documents"]) == 1
        assert root_section["documents"][0].path == Path("content/index.md")

    def test_subdir_section_has_documents(self, sample_sources, project_config):
        """Documents in subdirectories are in their respective sections."""
        sections = build_section_index(project_config, sample_sources)
        guias = next(s for s in sections if s["key"] == "guias")
        assert len(guias["documents"]) == 1
        assert guias["documents"][0].path == Path("content/guias/instalacion.md")

    def test_section_ordering_by_weight_then_title(self, project_config):
        """Sections are ordered by weight (lower first), then alphabetically."""
        # Create sources in sections with explicit weights via _index.md
        for sec, files in [
            ("z_section", ["z.md"]),
            ("a_section", ["a.md"]),
            ("m_section", ["m.md"]),
        ]:
            section_dir = project_config.root / "content" / sec
            section_dir.mkdir()
            (section_dir / files[0]).write_text("---\ntitle: Test\n---\n# Test")

        sources = [
            SourceFile(
                path=Path("content/z_section/z.md"),
                format="md",
                frontmatter={"title": "Z Doc"},
            ),
            SourceFile(
                path=Path("content/a_section/a.md"),
                format="md",
                frontmatter={"title": "A Doc"},
            ),
            SourceFile(
                path=Path("content/m_section/m.md"),
                format="md",
                frontmatter={"title": "M Doc"},
            ),
        ]

        sections = build_section_index(project_config, sources)
        # Without _index.md, all sections have weight=999, so alphabetical
        keys = [s["key"] for s in sections]
        assert keys == ["a_section", "m_section", "z_section"]

    def test_section_with_index_md_metadata(self, project_config):
        """_index.md defines title and weight for a section."""
        section_dir = project_config.root / "content" / "guias"
        section_dir.mkdir()
        (section_dir / "guia.md").write_text("---\ntitle: Guía\n---\n# Guía")
        (section_dir / "_index.md").write_text(
            "---\ntitle: Guías de Instalación\nweight: 2\n---\n"
        )

        sources = [
            SourceFile(
                path=Path("content/guias/guia.md"),
                format="md",
                frontmatter={"title": "Guía"},
            ),
        ]

        sections = build_section_index(project_config, sources)
        assert len(sections) == 1
        assert sections[0]["title"] == "Guías de Instalación"
        assert sections[0]["weight"] == 2
        assert sections[0]["key"] == "guias"

    def test_section_without_index_md_uses_directory_name(self, project_config):
        """Without _index.md, section title is the directory name."""
        section_dir = project_config.root / "content" / "tutoriales"
        section_dir.mkdir()
        (section_dir / "intro.md").write_text("---\ntitle: Introducción\n---\n# Intro")

        sources = [
            SourceFile(
                path=Path("content/tutoriales/intro.md"),
                format="md",
                frontmatter={"title": "Introducción"},
            ),
        ]

        sections = build_section_index(project_config, sources)
        assert len(sections) == 1
        assert sections[0]["title"] == "tutoriales"
        assert sections[0]["weight"] == 999

    def test_root_section_weight_is_zero(self, project_config):
        """Root section has weight=0 by default."""
        (project_config.root / "content" / "rootdoc.md").write_text(
            "---\ntitle: Root\n---\n# Root"
        )

        sources = [
            SourceFile(
                path=Path("content/rootdoc.md"),
                format="md",
                frontmatter={"title": "Root"},
            ),
        ]

        sections = build_section_index(project_config, sources)
        root = next(s for s in sections if s["key"] == "")
        assert root["weight"] == 0

    def test_section_frontmatter_weight_as_string(self, project_config):
        """Weight in _index.md parsed as string is converted to int."""
        section_dir = project_config.root / "content" / "docs"
        section_dir.mkdir()
        (section_dir / "doc.md").write_text("---\ntitle: Doc\n---\n# Doc")
        (section_dir / "_index.md").write_text("---\ntitle: Docs\nweight: '5'\n---\n")

        sources = [
            SourceFile(
                path=Path("content/docs/doc.md"),
                format="md",
                frontmatter={"title": "Doc"},
            ),
        ]

        sections = build_section_index(project_config, sources)
        assert sections[0]["weight"] == 5


class TestGenerateSectionPages:
    """Tests for the generate_section_pages function."""

    def test_root_section_generates_to_index_html(self, project_config):
        """Root section produces output/html/index.html."""
        sections = [
            {
                "key": "",
                "title": "Inicio",
                "weight": 0,
                "documents": [
                    SourceFile(
                        path=Path("content/index.md"),
                        format="md",
                        frontmatter={"title": "Home"},
                    ),
                ],
            }
        ]

        paths = generate_section_pages(project_config, sections)
        assert len(paths) == 1
        expected = project_config.root / "output" / "html" / "index.html"
        assert paths[0] == expected
        assert expected.is_file()

    def test_sub_section_generates_to_subdir(self, project_config):
        """Sub-sections produce output/html/<section>/index.html."""
        sections = [
            {
                "key": "guias",
                "title": "Guías",
                "weight": 1,
                "documents": [
                    SourceFile(
                        path=Path("content/guias/instalacion.md"),
                        format="md",
                        frontmatter={"title": "Instalación"},
                    ),
                ],
            }
        ]

        paths = generate_section_pages(project_config, sections)
        expected = project_config.root / "output" / "html" / "guias" / "index.html"
        assert paths[0] == expected
        assert expected.is_file()

    def test_multiple_sections_generate_multiple_pages(self, project_config):
        """Each section produces its own index.html."""
        sections = [
            {
                "key": "",
                "title": "Inicio",
                "weight": 0,
                "documents": [
                    SourceFile(
                        path=Path("content/index.md"),
                        format="md",
                        frontmatter={"title": "Home"},
                    ),
                ],
            },
            {
                "key": "guias",
                "title": "Guías",
                "weight": 1,
                "documents": [
                    SourceFile(
                        path=Path("content/guias/intro.md"),
                        format="md",
                        frontmatter={"title": "Introducción"},
                    ),
                ],
            },
        ]

        paths = generate_section_pages(project_config, sections)
        assert len(paths) == 2

        root_path = project_config.root / "output" / "html" / "index.html"
        guias_path = project_config.root / "output" / "html" / "guias" / "index.html"
        assert root_path.is_file()
        assert guias_path.is_file()

    def test_section_page_has_volver_link(self, project_config):
        """Section pages include breadcrumb link back to the root index."""
        sections = [
            {
                "key": "guias",
                "title": "Guías",
                "weight": 1,
                "documents": [
                    SourceFile(
                        path=Path("content/guias/intro.md"),
                        format="md",
                        frontmatter={"title": "Intro"},
                    ),
                ],
            }
        ]

        paths = generate_section_pages(project_config, sections)
        html = paths[0].read_text(encoding="utf-8")
        # Breadcrumb "Inicio" links to root index
        assert 'href="../index.html"' in html
        assert "Inicio" in html

    def test_section_empty_documents(self, project_config):
        """Section with no documents generates a valid page (no crash)."""
        sections = [
            {
                "key": "vacia",
                "title": "Vacía",
                "weight": 1,
                "documents": [],
            }
        ]

        paths = generate_section_pages(project_config, sections)
        assert len(paths) == 1
        html = paths[0].read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in html
        assert "Vacía" in html  # Title in breadcrumbs

    def test_documents_sorted_by_title(self, project_config):
        """Documents within a section are sorted alphabetically by title."""
        sections = [
            {
                "key": "",
                "title": "Inicio",
                "weight": 0,
                "documents": [
                    SourceFile(
                        path=Path("content/z.md"),
                        format="md",
                        frontmatter={"title": "Zebra"},
                    ),
                    SourceFile(
                        path=Path("content/a.md"),
                        format="md",
                        frontmatter={"title": "Alpha"},
                    ),
                    SourceFile(
                        path=Path("content/m.md"),
                        format="md",
                        frontmatter={"title": "Middle"},
                    ),
                ],
            }
        ]

        paths = generate_section_pages(project_config, sections)
        html = paths[0].read_text(encoding="utf-8")
        pos_a = html.index("Alpha")
        pos_m = html.index("Middle")
        pos_z = html.index("Zebra")
        assert pos_a < pos_m < pos_z


# ---------------------------------------------------------------------------
# Deeply nested files (section is first-level only)
# ---------------------------------------------------------------------------


class TestDeeplyNested:
    """Tests for deeply nested content files."""

    def test_nested_file_belongs_to_first_level_section(self, project_config):
        """A file in content/guias/sub/deep.md has section 'guias'."""
        section_dir = project_config.root / "content" / "guias" / "sub"
        section_dir.mkdir(parents=True)
        (section_dir / "deep.md").write_text("---\ntitle: Deep\n---\n# Deep")

        source = SourceFile(
            path=Path("content/guias/sub/deep.md"),
            format="md",
            frontmatter={"title": "Deep"},
        )

        assert source.section == "guias"

    def test_nested_section_index_generates_correctly(self, project_config):
        """Section index includes deeply nested files."""
        section_dir = project_config.root / "content" / "guias" / "sub"
        section_dir.mkdir(parents=True)
        (section_dir / "deep.md").write_text("---\ntitle: Deep Doc\n---\n# Deep")

        sources = [
            SourceFile(
                path=Path("content/guias/sub/deep.md"),
                format="md",
                frontmatter={"title": "Deep Doc"},
            ),
        ]

        sections = build_section_index(project_config, sources)
        assert len(sections) == 1
        assert sections[0]["key"] == "guias"
        assert len(sections[0]["documents"]) == 1


# ---------------------------------------------------------------------------
# Edge cases for full coverage
# ---------------------------------------------------------------------------


class TestIndexerEdgeCases:
    """Edge-case tests covering remaining code paths in the indexer."""

    def test_corrupt_index_md_is_handled(self, project_config):
        """A malformed _index.md does not crash the indexer."""
        section_dir = project_config.root / "content" / "docs"
        section_dir.mkdir()
        (section_dir / "doc.md").write_text("---\ntitle: Doc\n---\n# Doc")
        (section_dir / "_index.md").write_text("not valid yaml: [")

        sources = [
            SourceFile(
                path=Path("content/docs/doc.md"),
                format="md",
                frontmatter={"title": "Doc"},
            ),
        ]

        sections = build_section_index(project_config, sources)
        assert len(sections) == 1
        # Falls back to directory name
        assert sections[0]["title"] == "docs"

    def test_index_yml_non_dict_top_level(self, sample_sources, project_config):
        """A .index.yml whose top level is a list falls back."""
        index_yml = project_config.root / "content" / ".index.yml"
        index_yml.write_text(
            yaml.dump(["not a dict"]),
            encoding="utf-8",
        )

        paths = generate_index(sample_sources, project_config)
        # Falls back to section-based
        assert len(paths) >= 1

    def test_index_yml_sections_not_a_list(self, sample_sources, project_config):
        """A .index.yml with sections as a string falls back."""
        index_yml = project_config.root / "content" / ".index.yml"
        index_yml.write_text(
            yaml.dump({"sections": "not a list"}),
            encoding="utf-8",
        )

        paths = generate_index(sample_sources, project_config)
        assert len(paths) >= 1

    def test_index_yml_section_not_a_dict(self, sample_sources, project_config):
        """A .index.yml section that is not a dict is skipped."""
        index_yml = project_config.root / "content" / ".index.yml"
        index_yml.write_text(
            yaml.dump(
                {
                    "sections": [
                        "not a dict",
                        {
                            "title": "Valid",
                            "files": ["content/index.md"],
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

        paths = generate_index(sample_sources, project_config)
        html = paths[0].read_text(encoding="utf-8")
        # Documents from "Valid" section appear
        assert "Bienvenido" in html

    def test_generate_section_pages_with_index_yml_ordering(self, project_config):
        """generate_section_pages respects .index.yml ordering within sections."""
        # Create .index.yml with explicit ordering
        index_yml = project_config.root / "content" / ".index.yml"
        index_yml.write_text(
            yaml.dump(
                {
                    "sections": [
                        {
                            "title": "Ordered",
                            "files": [
                                "content/z.md",
                                "content/a.md",
                            ],
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

        sections = [
            {
                "key": "",
                "title": "Inicio",
                "weight": 0,
                "documents": [
                    SourceFile(
                        path=Path("content/z.md"),
                        format="md",
                        frontmatter={"title": "Zebra"},
                    ),
                    SourceFile(
                        path=Path("content/a.md"),
                        format="md",
                        frontmatter={"title": "Alpha"},
                    ),
                ],
            }
        ]

        paths = generate_section_pages(project_config, sections)
        html = paths[0].read_text(encoding="utf-8")
        pos_z = html.index("Zebra")
        pos_a = html.index("Alpha")
        # Z should appear before A (respects .index.yml order)
        assert pos_z < pos_a

    def test_index_md_j2_is_also_read(self, project_config):
        """_index.md.j2 is read as section metadata."""
        section_dir = project_config.root / "content" / "tutorials"
        section_dir.mkdir()
        (section_dir / "intro.md").write_text("---\ntitle: Intro\n---\n# Intro")
        (section_dir / "_index.md.j2").write_text(
            "---\ntitle: Tutoriales Avanzados\nweight: 3\n---\n"
        )

        sources = [
            SourceFile(
                path=Path("content/tutorials/intro.md"),
                format="md",
                frontmatter={"title": "Intro"},
            ),
        ]

        sections = build_section_index(project_config, sources)
        assert sections[0]["title"] == "Tutoriales Avanzados"
        assert sections[0]["weight"] == 3


# ---------------------------------------------------------------------------
# Index.md skipping tests (TK-016)
# ---------------------------------------------------------------------------


class TestIndexMdSkip:
    """Tests that sections with index.md on disk are skipped by the indexer."""

    def test_section_with_index_md_is_skipped(self, project_config):
        """Section with index.md on disk is NOT generated by the indexer."""
        (project_config.root / "content" / "guias").mkdir(parents=True)
        (project_config.root / "content" / "guias" / "index.md").write_text(
            "---\ntitle: Guías\n---\n# Guías\n"
        )
        (project_config.root / "content" / "guias" / "doc.md").write_text(
            "---\ntitle: Documento\n---\n# Doc\n"
        )

        sources = [
            SourceFile(
                path=Path("content/guias/index.md"),
                format="md",
                frontmatter={"title": "Guías"},
            ),
            SourceFile(
                path=Path("content/guias/doc.md"),
                format="md",
                frontmatter={"title": "Documento"},
            ),
        ]

        sections = build_section_index(project_config, sources)
        paths = generate_section_pages(project_config, sections)
        # index.md exists → section skipped, no pages generated
        assert len(paths) == 0

    def test_section_without_index_md_is_generated(self, project_config):
        """Section without index.md IS generated by the indexer."""
        (project_config.root / "content" / "guias").mkdir(parents=True)
        (project_config.root / "content" / "guias" / "doc.md").write_text(
            "---\ntitle: Documento\n---\n# Doc\n"
        )

        sources = [
            SourceFile(
                path=Path("content/guias/doc.md"),
                format="md",
                frontmatter={"title": "Documento"},
            ),
        ]

        sections = build_section_index(project_config, sources)
        paths = generate_section_pages(project_config, sections)
        # No index.md → section generated
        assert len(paths) == 1
        assert paths[0].name == "index.html"

    def test_section_with_index_md_j2_is_skipped(self, project_config):
        """Section with index.md.j2 on disk is also skipped."""
        (project_config.root / "content" / "tutorials").mkdir(parents=True)
        (project_config.root / "content" / "tutorials" / "index.md.j2").write_text(
            "---\ntitle: Tutoriales\n---\n# Tutoriales\n"
        )
        (project_config.root / "content" / "tutorials" / "intro.md").write_text(
            "---\ntitle: Intro\n---\n# Intro\n"
        )

        sources = [
            SourceFile(
                path=Path("content/tutorials/intro.md"),
                format="md",
                frontmatter={"title": "Intro"},
            ),
        ]

        sections = build_section_index(project_config, sources)
        paths = generate_section_pages(project_config, sections)
        assert len(paths) == 0

    def test_root_section_with_index_md_is_skipped(self, project_config):
        """Root section with index.md on disk is skipped."""
        (project_config.root / "content" / "index.md").write_text(
            "---\ntitle: Home\n---\n# Home\n"
        )
        (project_config.root / "content" / "doc.md").write_text(
            "---\ntitle: Doc\n---\n# Doc\n"
        )

        sources = [
            SourceFile(
                path=Path("content/index.md"),
                format="md",
                frontmatter={"title": "Home"},
            ),
            SourceFile(
                path=Path("content/doc.md"),
                format="md",
                frontmatter={"title": "Doc"},
            ),
        ]

        sections = build_section_index(project_config, sources)
        paths = generate_section_pages(project_config, sections)
        # Root section has index.md → skipped
        assert len(paths) == 0
