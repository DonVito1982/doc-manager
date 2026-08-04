"""Unit tests for the converter module."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from documentos.build.collector import SourceFile
from documentos.build.converter import (
    BuildResult,
    ConvertedFile,
    _build_document_list,
    _build_html_context,
    _create_jinja_env,
    _escape_xml,
    _generate_epub_metadata,
    _make_output_path,
    _resolve_latex_template_path,
    convert,
)
from documentos.config import ProjectConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(tmp_path: Path, formats: list[str] | None = None) -> ProjectConfig:
    """Create a minimal ProjectConfig rooted at *tmp_path*."""
    config = ProjectConfig(root=tmp_path)
    if formats is not None:
        config.output.formats = formats
    return config


def _make_source_file(relative_path: str, fmt: str = "md") -> SourceFile:
    """Create a SourceFile with the given relative path."""
    return SourceFile(path=Path(relative_path), format=fmt)


# ---------------------------------------------------------------------------
# ConvertedFile
# ---------------------------------------------------------------------------


class TestConvertedFile:
    """Tests for the ConvertedFile dataclass."""

    def test_creation_defaults(self) -> None:
        cf = ConvertedFile(
            source=Path("content/index.md"),
            format="html",
            output=Path("output/html/index.html"),
            success=True,
        )
        assert cf.source == Path("content/index.md")
        assert cf.format == "html"
        assert cf.output == Path("output/html/index.html")
        assert cf.success is True
        assert cf.error is None

    def test_creation_with_error(self) -> None:
        cf = ConvertedFile(
            source=Path("content/doc.md"),
            format="pdf",
            output=Path("output/pdf/doc.pdf"),
            success=False,
            error="latexmk not found",
        )
        assert cf.error == "latexmk not found"
        assert cf.success is False

    def test_creation_with_values(self) -> None:
        cf = ConvertedFile(
            source=Path("content/guia/intro.md"),
            format="epub",
            output=Path("output/epub/guia/intro.epub"),
            success=True,
        )
        assert cf.source == Path("content/guia/intro.md")
        assert cf.format == "epub"
        assert cf.output == Path("output/epub/guia/intro.epub")


# ---------------------------------------------------------------------------
# BuildResult
# ---------------------------------------------------------------------------


class TestBuildResult:
    """Tests for the BuildResult dataclass."""

    def test_creation_with_defaults(self) -> None:
        br = BuildResult()
        assert br.converted == []
        assert br.errors == []
        assert br.warnings == []
        assert br.output_dir == Path()

    def test_creation_with_values(self) -> None:
        cf = ConvertedFile(
            source=Path("content/index.md"),
            format="html",
            output=Path("output/html/index.html"),
            success=True,
        )
        br = BuildResult(
            converted=[cf],
            errors=["Pandoc not found"],
            warnings=["LaTeX missing"],
            output_dir=Path("output"),
        )
        assert len(br.converted) == 1
        assert br.errors == ["Pandoc not found"]
        assert br.warnings == ["LaTeX missing"]
        assert br.output_dir == Path("output")


# ---------------------------------------------------------------------------
# convert() — happy path
# ---------------------------------------------------------------------------


class TestConvertHappyPath:
    """Happy-path tests for the convert() function."""

    def test_html_only(self, tmp_path: Path) -> None:
        """Convert to HTML with mocked pypandoc."""
        config = _make_config(tmp_path, formats=["html"])
        source = _make_source_file("content/index.md")

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_text",
                return_value="<html><body><p>Hello</p></body></html>",
            ),
        ):
            results = convert(source, config, "# Hello\n")

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].format == "html"
        assert results[0].source == Path("content/index.md")
        assert results[0].output == Path("output/html/index.html")
        assert results[0].error is None

        # Verify output file was written
        output_file = tmp_path / "output/html/index.html"
        assert output_file.is_file()
        content = output_file.read_text(encoding="utf-8")
        assert "<html>" in content

    def test_epub_only(self, tmp_path: Path) -> None:
        """Convert to EPUB with mocked pypandoc.convert_file."""
        config = _make_config(tmp_path, formats=["epub"])
        source = _make_source_file("content/index.md")

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_file",
            ) as mock_convert_file,
        ):
            results = convert(source, config, "# Hello\n")

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].format == "epub"
        assert results[0].output == Path("output/epub/index.epub")
        mock_convert_file.assert_called_once()
        call_kwargs = mock_convert_file.call_args[1]
        assert call_kwargs["to"] == "epub"
        assert call_kwargs["format"] == "markdown"
        assert any("--toc" in arg for arg in call_kwargs["extra_args"])
        assert any("--epub-metadata=" in arg for arg in call_kwargs["extra_args"])

    def test_pdf_only(self, tmp_path: Path) -> None:
        """Convert to PDF with mocked pandoc and latexmk."""
        config = _make_config(tmp_path, formats=["pdf"])
        source = _make_source_file("content/index.md")

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_text",
                return_value=r"\documentclass{article}\begin{document}Hello\end{document}",
            ),
            patch(
                "documentos.build.converter.shutil.which",
                return_value="/usr/bin/latexmk",
            ),
            patch(
                "documentos.build.converter.subprocess.run",
            ) as mock_run,
        ):
            # Simulate latexmk creating the PDF
            def _create_pdf(*args, **kwargs):
                cwd = kwargs.get("cwd", ".")
                (Path(cwd) / "index.pdf").write_text("PDF content", encoding="utf-8")
                return MagicMock()

            mock_run.side_effect = _create_pdf

            results = convert(source, config, "# Hello\n")

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].format == "pdf"
        assert results[0].output == Path("output/pdf/index.pdf")

    def test_all_three_formats(self, tmp_path: Path) -> None:
        """Convert to HTML, EPUB, and PDF simultaneously."""
        config = _make_config(tmp_path, formats=["html", "epub", "pdf"])
        source = _make_source_file("content/index.md")

        def _create_pdf(*args, **kwargs):
            cwd = kwargs.get("cwd", ".")
            (Path(cwd) / "index.pdf").write_text("PDF", encoding="utf-8")
            return MagicMock()

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_text",
                return_value="<html>OK</html>",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_file",
            ),
            patch(
                "documentos.build.converter.shutil.which",
                return_value="/usr/bin/latexmk",
            ),
            patch(
                "documentos.build.converter.subprocess.run",
                side_effect=_create_pdf,
            ),
        ):
            results = convert(source, config, "# Hello\n")

        assert len(results) == 3
        formats = {r.format for r in results}
        assert formats == {"html", "epub", "pdf"}
        assert all(r.success for r in results)

    def test_with_html_template_present(self, tmp_path: Path) -> None:
        """Verify --template is passed when pandoc.html exists."""
        config = _make_config(tmp_path, formats=["html"])
        source = _make_source_file("content/index.md")

        # Create the template file
        templates_dir = tmp_path / config.templates.dir
        templates_dir.mkdir(parents=True)
        (templates_dir / "pandoc.html").write_text("<html>$body$</html>")

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_text",
                return_value="<html>templated</html>",
            ) as mock_convert,
        ):
            convert(source, config, "# Hello\n")

        call_args = mock_convert.call_args[1]
        assert any("--template=" in arg for arg in call_args["extra_args"])

    def test_with_latex_template_from_config(self, tmp_path: Path) -> None:
        """Verify --template is passed from config.pdf.template."""
        config = _make_config(tmp_path, formats=["pdf"])
        source = _make_source_file("content/index.md")

        # Create a custom template
        custom_template = tmp_path / "custom.latex"
        custom_template.write_text("% custom template")

        config.pdf.template = "custom.latex"

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_text",
                return_value=r"\documentclass{article}\begin{document}Test\end{document}",
            ) as mock_convert,
            patch(
                "documentos.build.converter.shutil.which",
                return_value="/usr/bin/latexmk",
            ),
            patch(
                "documentos.build.converter.subprocess.run",
            ),
        ):
            convert(source, config, "# Hello\n")

        latex_extra = mock_convert.call_args[1]["extra_args"]
        assert any("--template=" in arg for arg in latex_extra)
        assert any("custom.latex" in arg for arg in latex_extra)

    def test_with_latex_template_default(self, tmp_path: Path) -> None:
        """Verify latex-template.tex from templates dir is used as default."""
        config = _make_config(tmp_path, formats=["pdf"])
        source = _make_source_file("content/index.md")

        templates_dir = tmp_path / config.templates.dir
        templates_dir.mkdir(parents=True)
        (templates_dir / "latex-template.tex").write_text("% default")

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_text",
                return_value=r"\documentclass{article}\begin{document}Test\end{document}",
            ) as mock_convert,
            patch(
                "documentos.build.converter.shutil.which",
                return_value="/usr/bin/latexmk",
            ),
            patch(
                "documentos.build.converter.subprocess.run",
            ),
        ):
            convert(source, config, "# Hello\n")

        latex_extra = mock_convert.call_args[1]["extra_args"]
        assert any("--template=" in arg for arg in latex_extra)
        assert any("latex-template.tex" in arg for arg in latex_extra)

    def test_with_pdf_header_and_footer(self, tmp_path: Path) -> None:
        """Verify header/footer variables are passed to Pandoc."""
        config = _make_config(tmp_path, formats=["pdf"])
        source = _make_source_file("content/index.md")

        config.pdf.header = "My Header"
        config.pdf.footer = "My Footer"

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_text",
                return_value=r"\documentclass{article}\begin{document}Test\end{document}",
            ) as mock_convert,
            patch(
                "documentos.build.converter.shutil.which",
                return_value="/usr/bin/latexmk",
            ),
            patch(
                "documentos.build.converter.subprocess.run",
            ),
        ):
            convert(source, config, "# Hello\n")

        latex_extra = mock_convert.call_args[1]["extra_args"]
        assert any("--variable=header=My Header" in arg for arg in latex_extra)
        assert any("--variable=footer=My Footer" in arg for arg in latex_extra)

    def test_pdf_saves_tex_file(self, tmp_path: Path) -> None:
        """Verify the intermediate .tex file is saved to output/tex/."""
        config = _make_config(tmp_path, formats=["pdf"])
        source = _make_source_file("content/index.md")

        def _create_pdf(*args, **kwargs):
            cwd = kwargs.get("cwd", ".")
            (Path(cwd) / "index.pdf").write_text("PDF", encoding="utf-8")
            return MagicMock()

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_text",
                return_value=r"\documentclass{article}\begin{document}Test\end{document}",
            ),
            patch(
                "documentos.build.converter.shutil.which",
                return_value="/usr/bin/latexmk",
            ),
            patch(
                "documentos.build.converter.subprocess.run",
                side_effect=_create_pdf,
            ),
        ):
            convert(source, config, "# Test\n")

        tex_file = tmp_path / "output/tex/index.tex"
        assert tex_file.is_file()
        tex_content = tex_file.read_text(encoding="utf-8")
        assert r"\documentclass" in tex_content
        assert r"\begin{document}" in tex_content

    def test_pdf_saves_tex_file_nested(self, tmp_path: Path) -> None:
        """Verify .tex file is saved with nested directory structure."""
        config = _make_config(tmp_path, formats=["pdf"])
        source = _make_source_file("content/guias/subseccion/deep.md")

        def _create_pdf(*args, **kwargs):
            cwd = kwargs.get("cwd", ".")
            (Path(cwd) / "deep.pdf").write_text("PDF", encoding="utf-8")
            return MagicMock()

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_text",
                return_value=r"\documentclass{article}\begin{document}Deep\end{document}",
            ),
            patch(
                "documentos.build.converter.shutil.which",
                return_value="/usr/bin/latexmk",
            ),
            patch(
                "documentos.build.converter.subprocess.run",
                side_effect=_create_pdf,
            ),
        ):
            convert(source, config, "# Deep\n")

        tex_file = tmp_path / "output/tex/guias/subseccion/deep.tex"
        assert tex_file.is_file()
        assert r"\documentclass" in tex_file.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# convert() — error cases
# ---------------------------------------------------------------------------


class TestConvertErrors:
    """Error-case tests for the convert() function."""

    def test_pandoc_not_installed(self, tmp_path: Path) -> None:
        """Verify RuntimeError when Pandoc is not available."""
        config = _make_config(tmp_path, formats=["html"])
        source = _make_source_file("content/index.md")

        with patch(
            "documentos.build.converter.pypandoc.get_pandoc_version",
            side_effect=OSError("pandoc not found"),
        ):
            with pytest.raises(RuntimeError, match="Pandoc is not installed"):
                convert(source, config, "# Hello\n")

    def test_latexmk_not_found_skips_pdf(self, tmp_path: Path, caplog) -> None:
        """When latexmk is missing, PDF is skipped but HTML/EPUB continue."""
        config = _make_config(tmp_path, formats=["html", "epub", "pdf"])
        source = _make_source_file("content/index.md")

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_text",
                return_value="<html>OK</html>",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_file",
            ),
            patch(
                "documentos.build.converter.shutil.which",
                return_value=None,  # latexmk not found
            ),
        ):
            with caplog.at_level(logging.WARNING):
                results = convert(source, config, "# Hello\n")

        assert len(results) == 3
        html_result = next(r for r in results if r.format == "html")
        epub_result = next(r for r in results if r.format == "epub")
        pdf_result = next(r for r in results if r.format == "pdf")

        assert html_result.success is True
        assert epub_result.success is True
        assert pdf_result.success is False
        assert "latexmk" in pdf_result.error.lower()
        assert "latexmk not found" in caplog.text

    def test_pypandoc_raises_during_html_conversion(self, tmp_path: Path) -> None:
        """When pypandoc raises, the result has success=False with error."""
        config = _make_config(tmp_path, formats=["html"])
        source = _make_source_file("content/index.md")

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_text",
                side_effect=RuntimeError("conversion error"),
            ),
        ):
            results = convert(source, config, "# Hello\n")

        assert len(results) == 1
        assert results[0].success is False
        assert "conversion error" in results[0].error

    def test_pypandoc_raises_during_epub_conversion(self, tmp_path: Path) -> None:
        """When pypandoc raises for EPUB, result is error but no crash."""
        config = _make_config(tmp_path, formats=["epub"])
        source = _make_source_file("content/index.md")

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_file",
                side_effect=RuntimeError("epub error"),
            ),
        ):
            results = convert(source, config, "# Hello\n")

        assert len(results) == 1
        assert results[0].success is False
        assert "epub error" in results[0].error

    def test_pdf_conversion_continues_after_latexmk_failure(
        self, tmp_path: Path
    ) -> None:
        """When latexmk fails, the PDF result has success=False."""
        config = _make_config(tmp_path, formats=["html", "pdf"])
        source = _make_source_file("content/index.md")

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_text",
                return_value="<html>OK</html>",
            ),
            patch(
                "documentos.build.converter.shutil.which",
                return_value="/usr/bin/latexmk",
            ),
            patch(
                "documentos.build.converter.subprocess.run",
                side_effect=Exception("latexmk crashed"),
            ),
        ):
            results = convert(source, config, "# Hello\n")

        assert len(results) == 2
        html_result = next(r for r in results if r.format == "html")
        pdf_result = next(r for r in results if r.format == "pdf")
        assert html_result.success is True
        assert pdf_result.success is False

    def test_empty_preprocessed_string(self, tmp_path: Path) -> None:
        """Empty content should not raise an exception."""
        config = _make_config(tmp_path, formats=["html"])
        source = _make_source_file("content/index.md")

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_text",
                return_value="<html><body></body></html>",
            ),
        ):
            results = convert(source, config, "")

        assert len(results) == 1
        assert results[0].success is True

    def test_tex_not_saved_when_latexmk_missing(self, tmp_path: Path, caplog) -> None:
        """When latexmk is missing, .tex file is NOT saved (early return)."""
        config = _make_config(tmp_path, formats=["pdf"])
        source = _make_source_file("content/index.md")

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.shutil.which",
                return_value=None,  # latexmk not found
            ),
        ):
            with caplog.at_level(logging.WARNING):
                results = convert(source, config, "# Hello\n")

        assert len(results) == 1
        assert results[0].success is False
        assert "latexmk" in results[0].error.lower()

        # The .tex file should NOT exist since we returned early
        tex_file = tmp_path / "output/tex/index.tex"
        assert not tex_file.is_file()


# ---------------------------------------------------------------------------
# _make_output_path
# ---------------------------------------------------------------------------


class TestMakeOutputPath:
    """Tests for the _make_output_path helper."""

    def test_simple_md_file(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        source = _make_source_file("content/index.md", fmt="md")
        result = _make_output_path(source, config, "html")
        assert result == Path("output/html/index.html")

    def test_j2_file(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        source = _make_source_file("content/guia/instalacion.md.j2", fmt="md.j2")
        result = _make_output_path(source, config, "html")
        assert result == Path("output/html/guia/instalacion.html")

    def test_deeply_nested_path(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        source = _make_source_file("content/a/b/c/doc.md", fmt="md")
        result = _make_output_path(source, config, "pdf")
        assert result == Path("output/pdf/a/b/c/doc.pdf")

    def test_epub_format(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        source = _make_source_file("content/index.md", fmt="md")
        result = _make_output_path(source, config, "epub")
        assert result == Path("output/epub/index.epub")

    def test_pdf_format(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        source = _make_source_file("content/index.md", fmt="md")
        result = _make_output_path(source, config, "pdf")
        assert result == Path("output/pdf/index.pdf")

    def test_tex_format(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        source = _make_source_file("content/index.md", fmt="md")
        result = _make_output_path(source, config, "tex")
        assert result == Path("output/tex/index.tex")

    def test_tex_format_nested(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        source = _make_source_file("content/guia/instalacion.md.j2", fmt="md.j2")
        result = _make_output_path(source, config, "tex")
        assert result == Path("output/tex/guia/instalacion.tex")

    def test_custom_output_dir(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        config.output.dir = "build_output"
        source = _make_source_file("content/index.md", fmt="md")
        result = _make_output_path(source, config, "html")
        assert result == Path("build_output/html/index.html")


# ---------------------------------------------------------------------------
# EPUB metadata
# ---------------------------------------------------------------------------


class TestEpubMetadata:
    """Tests for the EPUB metadata generation."""

    def test_generates_metadata_xml(self, tmp_path: Path) -> None:
        """Verify metadata XML is generated with correct fields."""
        config = _make_config(tmp_path)
        config.project.title = "My Project"
        config.project.author = "Author Name"
        config.project.language = "es"

        metadata_path = _generate_epub_metadata(config)
        try:
            content = metadata_path.read_text(encoding="utf-8")
            assert "<dc:title>My Project</dc:title>" in content
            assert "<dc:creator>Author Name</dc:creator>" in content
            assert "<dc:language>es</dc:language>" in content
            assert 'xmlns:dc="http://purl.org/dc/elements/1.1/"' in content
        finally:
            metadata_path.unlink(missing_ok=True)

    def test_xml_special_characters_escaped(self, tmp_path: Path) -> None:
        """Verify XML special characters are escaped in metadata."""
        config = _make_config(tmp_path)
        config.project.title = "A & B < C"
        config.project.author = 'Author "X"'
        config.project.language = "en"

        metadata_path = _generate_epub_metadata(config)
        try:
            content = metadata_path.read_text(encoding="utf-8")
            assert "<dc:title>A &amp; B &lt; C</dc:title>" in content
            assert "<dc:creator>Author &#34;X&#34;</dc:creator>" in content
        finally:
            metadata_path.unlink(missing_ok=True)

    def test_epub_metadata_passed_to_pandoc(self, tmp_path: Path) -> None:
        """Verify the metadata file path is passed as --epub-metadata."""
        config = _make_config(tmp_path, formats=["epub"])
        source = _make_source_file("content/index.md")
        config.project.title = "Test"
        config.project.author = "Tester"
        config.project.language = "en"

        captured_content: list[str] = []

        def _capture_metadata(source_path, to, format, outputfile, extra_args):
            meta_arg = next(a for a in extra_args if a.startswith("--epub-metadata="))
            meta_path = Path(meta_arg.split("=", 1)[1])
            captured_content.append(meta_path.read_text(encoding="utf-8"))

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_file",
                side_effect=_capture_metadata,
            ),
        ):
            convert(source, config, "# Hello\n")

        assert len(captured_content) == 1
        assert "Test" in captured_content[0]
        assert "Tester" in captured_content[0]
        assert "en" in captured_content[0]

    def test_metadata_temp_file_cleaned_up(self, tmp_path: Path) -> None:
        """Verify the temp metadata file is removed after conversion."""
        config = _make_config(tmp_path, formats=["epub"])
        config.project.title = "Test"
        source = _make_source_file("content/index.md")

        metadata_paths: list[Path] = []

        def _track_metadata(source_path, to, format, outputfile, extra_args):
            meta_arg = next(a for a in extra_args if a.startswith("--epub-metadata="))
            meta_path = Path(meta_arg.split("=", 1)[1])
            metadata_paths.append(meta_path)

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_file",
                side_effect=_track_metadata,
            ),
        ):
            convert(source, config, "# Hello\n")

        assert len(metadata_paths) == 1
        assert not metadata_paths[0].exists()


# ---------------------------------------------------------------------------
# _escape_xml
# ---------------------------------------------------------------------------


class TestEscapeXml:
    """Tests for the _escape_xml helper."""

    def test_no_special_chars(self) -> None:
        assert _escape_xml("Hello World") == "Hello World"

    def test_ampersand(self) -> None:
        assert _escape_xml("A & B") == "A &amp; B"

    def test_less_than(self) -> None:
        assert _escape_xml("x < y") == "x &lt; y"

    def test_greater_than(self) -> None:
        assert _escape_xml("x > y") == "x &gt; y"

    def test_quotes(self) -> None:
        assert _escape_xml('"hello"') == "&quot;hello&quot;"

    def test_apostrophe(self) -> None:
        assert _escape_xml("it's") == "it&apos;s"

    def test_mixed_special_chars(self) -> None:
        assert _escape_xml('A & B < C > D "E"') == (
            "A &amp; B &lt; C &gt; D &quot;E&quot;"
        )


# ---------------------------------------------------------------------------
# Output file verification
# ---------------------------------------------------------------------------


class TestOutputFileCreation:
    """Verify that output files are created on disk."""

    def test_html_output_written(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, formats=["html"])
        source = _make_source_file("content/index.md")

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_text",
                return_value="<html><body>Content</body></html>",
            ),
        ):
            convert(source, config, "# Content\n")

        output_file = tmp_path / "output/html/index.html"
        assert output_file.is_file()
        content = output_file.read_text(encoding="utf-8")
        assert "Content" in content

    def test_nested_output_directory_created(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, formats=["html"])
        source = _make_source_file("content/guias/subseccion/deep.md")

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_text",
                return_value="<html>OK</html>",
            ),
        ):
            convert(source, config, "# OK\n")

        output_file = tmp_path / "output/html/guias/subseccion/deep.html"
        assert output_file.is_file()

    def test_pdf_output_written(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, formats=["pdf"])
        source = _make_source_file("content/report.md")

        def _create_pdf(*args, **kwargs):
            cwd = kwargs.get("cwd", ".")
            (Path(cwd) / "report.pdf").write_text("PDF data", encoding="utf-8")
            return MagicMock()

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_text",
                return_value=r"\documentclass{article}\begin{document}Report\end{document}",
            ),
            patch(
                "documentos.build.converter.shutil.which",
                return_value="/usr/bin/latexmk",
            ),
            patch(
                "documentos.build.converter.subprocess.run",
                side_effect=_create_pdf,
            ),
        ):
            convert(source, config, "# Report\n")

        output_file = tmp_path / "output/pdf/report.pdf"
        assert output_file.is_file()
        assert output_file.read_text(encoding="utf-8") == "PDF data"


# ---------------------------------------------------------------------------
# Integration-style tests
# ---------------------------------------------------------------------------


class TestConvertIntegration:
    """Tests covering combined scenarios and edge cases."""

    def test_format_order_preserved(self, tmp_path: Path) -> None:
        """Results should appear in the order of config.output.formats."""
        config = _make_config(tmp_path, formats=["pdf", "html", "epub"])
        source = _make_source_file("content/index.md")

        def _create_pdf(*args, **kwargs):
            cwd = kwargs.get("cwd", ".")
            (Path(cwd) / "index.pdf").write_text("PDF", encoding="utf-8")
            return MagicMock()

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_text",
                return_value="<html>OK</html>",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_file",
            ),
            patch(
                "documentos.build.converter.shutil.which",
                return_value="/usr/bin/latexmk",
            ),
            patch(
                "documentos.build.converter.subprocess.run",
                side_effect=_create_pdf,
            ),
        ):
            results = convert(source, config, "# Hello\n")

        assert [r.format for r in results] == ["pdf", "html", "epub"]

    def test_convert_respects_config_output_dir(self, tmp_path: Path) -> None:
        """Output files go to the directory specified in config.output.dir."""
        config = _make_config(tmp_path, formats=["html"])
        config.output.dir = "build"
        source = _make_source_file("content/index.md")

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_text",
                return_value="<html>OK</html>",
            ),
        ):
            results = convert(source, config, "# OK\n")

        assert results[0].output == Path("build/html/index.html")
        output_file = tmp_path / "build/html/index.html"
        assert output_file.is_file()

    def test_latexmk_called_with_correct_args(self, tmp_path: Path) -> None:
        """Verify latexmk is invoked with correct flags."""
        config = _make_config(tmp_path, formats=["pdf"])
        source = _make_source_file("content/doc.md")

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_text",
                return_value=r"\documentclass{article}\begin{document}Test\end{document}",
            ),
            patch(
                "documentos.build.converter.shutil.which",
                return_value="/usr/bin/latexmk",
            ),
            patch(
                "documentos.build.converter.subprocess.run",
            ) as mock_run,
        ):
            convert(source, config, "# Test\n")

        mock_run.assert_called_once()
        cmd_args = mock_run.call_args[0][0]
        assert "latexmk" in cmd_args
        assert "-pdfxe" in cmd_args
        assert "-interaction=nonstopmode" in cmd_args

    def test_math_packages_in_latex_header(self, tmp_path: Path) -> None:
        """Verify math packages are written to the --include-in-header temp file."""
        config = _make_config(tmp_path, formats=["pdf"])
        source = _make_source_file("content/doc.md")

        written_content: list[str] = []

        class _CaptureTempFile:
            name = str(tmp_path / "math_header.tex")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def write(self, data: str):
                written_content.append(data)

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_text",
                return_value=r"\documentclass{article}\begin{document}Test\end{document}",
            ) as mock_convert,
            patch(
                "documentos.build.converter.shutil.which",
                return_value="/usr/bin/latexmk",
            ),
            patch(
                "documentos.build.converter.subprocess.run",
            ),
            patch(
                "documentos.build.converter.tempfile.NamedTemporaryFile",
                return_value=_CaptureTempFile(),
            ),
        ):
            convert(source, config, "# Test\n")

        # Verify --include-in-header was passed with a file path (not raw text)
        extra_args = mock_convert.call_args[1]["extra_args"]
        assert any("--include-in-header=" in a for a in extra_args)

        # Verify the math packages were written to the temp file
        assert len(written_content) == 1
        assert "amsmath" in written_content[0]
        assert "amssymb" in written_content[0]
        assert "unicode-math" in written_content[0]

    def test_html_template_flag_always_present(self, tmp_path: Path) -> None:
        """The base.html Jinja2 template is always rendered and passed to Pandoc."""
        config = _make_config(tmp_path, formats=["html"])
        source = _make_source_file("content/index.md")

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_text",
                return_value="<html>OK</html>",
            ) as mock_convert,
        ):
            convert(source, config, "# OK\n")

        extra_args = mock_convert.call_args[1]["extra_args"]
        assert any("--template=" in a for a in extra_args)


# ---------------------------------------------------------------------------
# Edge cases for full coverage
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge-case tests to cover remaining code paths."""

    def test_unsupported_format_in_config(self, tmp_path: Path) -> None:
        """An unsupported format in config returns error ConvertedFile."""
        config = _make_config(tmp_path, formats=["docx"])
        source = _make_source_file("content/index.md")

        with patch(
            "documentos.build.converter.pypandoc.get_pandoc_version",
            return_value="3.1.2",
        ):
            results = convert(source, config, "# Hello\n")

        assert len(results) == 1
        assert results[0].success is False
        assert "Unsupported" in results[0].error
        assert results[0].format == "docx"

    def test_latexmk_timeout(self, tmp_path: Path) -> None:
        """When latexmk times out, PDF result has success=False."""
        config = _make_config(tmp_path, formats=["pdf"])
        source = _make_source_file("content/doc.md")

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_text",
                return_value=r"\documentclass{article}\begin{document}T\end{document}",
            ),
            patch(
                "documentos.build.converter.shutil.which",
                return_value="/usr/bin/latexmk",
            ),
            patch(
                "documentos.build.converter.subprocess.run",
                side_effect=__import__("subprocess").TimeoutExpired("latexmk", 120),
            ),
        ):
            results = convert(source, config, "# Hello\n")

        assert len(results) == 1
        assert results[0].success is False
        assert "timed out" in results[0].error.lower()

    def test_latexmk_produces_no_pdf(self, tmp_path: Path) -> None:
        """When latexmk succeeds but produces no PDF, result is error."""
        config = _make_config(tmp_path, formats=["pdf"])
        source = _make_source_file("content/doc.md")

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_text",
                return_value=r"\documentclass{article}\begin{document}T\end{document}",
            ),
            patch(
                "documentos.build.converter.shutil.which",
                return_value="/usr/bin/latexmk",
            ),
            patch(
                "documentos.build.converter.subprocess.run",
                return_value=MagicMock(),
            ),
        ):
            results = convert(source, config, "# Hello\n")

        assert len(results) == 1
        assert results[0].success is False
        assert "did not produce a PDF" in results[0].error


# ---------------------------------------------------------------------------
# Template rendering tests (TK-008)
# ---------------------------------------------------------------------------


class TestJinjaEnv:
    """Tests for the Jinja2 environment creation."""

    def test_creates_env_with_packaged_templates(self, tmp_path: Path) -> None:
        """The environment can load the packaged base.html template."""
        config = _make_config(tmp_path)
        env = _create_jinja_env(config)
        template = env.get_template("base.html")
        assert template is not None

    def test_creates_env_with_user_templates(self, tmp_path: Path) -> None:
        """User templates directory is included in the loader."""
        config = _make_config(tmp_path)
        user_dir = tmp_path / config.templates.dir
        user_dir.mkdir(parents=True)
        (user_dir / "custom.html").write_text("<html>{{ title }}</html>")

        env = _create_jinja_env(config)
        template = env.get_template("custom.html")
        rendered = template.render(title="Test")
        assert "<html>Test</html>" in rendered

    def test_user_template_overrides_packaged(self, tmp_path: Path) -> None:
        """A user-provided base.html overrides the packaged one."""
        config = _make_config(tmp_path)
        user_dir = tmp_path / config.templates.dir
        user_dir.mkdir(parents=True)
        (user_dir / "base.html").write_text("<html><body>CUSTOM</body></html>")

        env = _create_jinja_env(config)
        template = env.get_template("base.html")
        rendered = template.render(
            project={"title": "T", "author": "A", "language": "es"},
            title="Doc",
            documents=[],
            assets="assets",
        )
        assert "CUSTOM" in rendered

    def test_env_loads_partials(self, tmp_path: Path) -> None:
        """The environment can resolve partials via {% include %}."""
        config = _make_config(tmp_path)
        env = _create_jinja_env(config)
        template = env.get_template("base.html")
        rendered = template.render(
            project={"title": "T", "author": "A", "language": "es"},
            title="Doc",
            documents=[],
            assets="assets",
        )
        assert "<nav" in rendered
        assert "sidebar" in rendered


class TestBuildDocumentList:
    """Tests for the _build_document_list helper."""

    def test_empty_list(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        result = _build_document_list([], config)
        assert result == []

    def test_single_document(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        sf = SourceFile(
            path=Path("content/index.md"),
            format="md",
            frontmatter={"title": "Home"},
        )
        result = _build_document_list([sf], config)
        assert len(result) == 1
        assert result[0]["title"] == "Home"
        assert result[0]["slug"] == "index.html"

    def test_falls_back_to_stem(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        sf = SourceFile(path=Path("content/guia/intro.md"), format="md")
        result = _build_document_list([sf], config)
        assert result[0]["title"] == "intro"

    def test_nested_documents(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        sf = SourceFile(
            path=Path("content/a/b/doc.md"),
            format="md",
            frontmatter={"title": "Deep Doc"},
        )
        result = _build_document_list([sf], config)
        assert result[0]["slug"] == "a/b/doc.html"

    def test_multiple_documents(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        docs = [
            SourceFile(
                path=Path("content/index.md"),
                format="md",
                frontmatter={"title": "Home"},
            ),
            SourceFile(
                path=Path("content/guia/intro.md"),
                format="md",
                frontmatter={"title": "Intro"},
            ),
        ]
        result = _build_document_list(docs, config)
        assert len(result) == 2
        assert result[0]["title"] == "Home"
        assert result[1]["title"] == "Intro"


class TestBuildHtmlContext:
    """Tests for the _build_html_context helper."""

    def test_context_without_documents(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        config.project.title = "My Project"
        config.project.author = "Author"
        config.project.language = "en"

        source = _make_source_file("content/index.md")
        source.frontmatter = {"title": "Welcome"}

        ctx = _build_html_context(source, config, None)
        assert ctx["project"]["title"] == "My Project"
        assert ctx["project"]["author"] == "Author"
        assert ctx["project"]["language"] == "en"
        assert ctx["title"] == "Welcome"
        assert ctx["documents"] == []
        assert ctx["assets"] == "assets"

    def test_context_with_documents(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        source = _make_source_file("content/index.md")
        source.frontmatter = {"title": "Home"}

        all_docs = [
            SourceFile(
                path=Path("content/index.md"),
                format="md",
                frontmatter={"title": "Home"},
            ),
            SourceFile(
                path=Path("content/about.md"),
                format="md",
                frontmatter={"title": "About"},
            ),
        ]

        ctx = _build_html_context(source, config, all_docs)
        assert len(ctx["documents"]) == 2
        assert ctx["documents"][0]["title"] == "Home"
        assert ctx["documents"][1]["title"] == "About"

    def test_context_title_fallback(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        source = _make_source_file("content/readme.md")
        ctx = _build_html_context(source, config, None)
        assert ctx["title"] == "readme"


class TestBaseHtmlTemplate:
    """Tests for the base.html Jinja2 template rendering."""

    def test_renders_html5_structure(self, tmp_path: Path) -> None:
        """The rendered template is valid HTML5 with expected elements."""
        config = _make_config(tmp_path)
        env = _create_jinja_env(config)
        rendered = env.get_template("base.html").render(
            project={"title": "Test Project", "author": "Tester", "language": "es"},
            title="My Document",
            documents=[],
            assets="assets",
        )
        assert "<!DOCTYPE html>" in rendered
        assert '<html lang="es">' in rendered
        assert "<title>My Document — Test Project</title>" in rendered
        assert '<link rel="stylesheet" href="assets/css/style.css">' in rendered
        assert "cdn.jsdelivr.net/npm/mathjax@3" in rendered
        assert "<header>" in rendered
        assert "<main>" in rendered
        assert "<footer>" in rendered
        assert "Tester" in rendered

    def test_body_placeholder_preserved(self, tmp_path: Path) -> None:
        """The $body$ placeholder is preserved for Pandoc replacement."""
        config = _make_config(tmp_path)
        env = _create_jinja_env(config)
        rendered = env.get_template("base.html").render(
            project={"title": "T", "author": "A", "language": "es"},
            title="Doc",
            documents=[],
            assets="assets",
        )
        assert "$body$" in rendered

    def test_sidebar_with_documents(self, tmp_path: Path) -> None:
        """Documents appear as links in the sidebar."""
        config = _make_config(tmp_path)
        env = _create_jinja_env(config)
        rendered = env.get_template("base.html").render(
            project={"title": "T", "author": "A", "language": "es"},
            title="Doc",
            documents=[
                {"title": "Home", "slug": "index.html"},
                {"title": "Guide", "slug": "guia/intro.html"},
            ],
            assets="assets",
        )
        assert '<a href="index.html">Home</a>' in rendered
        assert '<a href="guia/intro.html">Guide</a>' in rendered

    def test_mathjax_config_external(self, tmp_path: Path) -> None:
        """MathJax configuration is loaded from an external file."""
        config = _make_config(tmp_path)
        env = _create_jinja_env(config)
        rendered = env.get_template("base.html").render(
            project={"title": "T", "author": "A", "language": "es"},
            title="Doc",
            documents=[],
            assets="assets",
        )
        assert 'src="assets/js/mathjax-config.js"' in rendered
        assert "cdn.jsdelivr.net/npm/mathjax@3" in rendered


class TestEpubMetadataTemplate:
    """Tests for the epub-metadata.xml Jinja2 template."""

    def test_renders_valid_xml(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        config.project.title = "My Book"
        config.project.author = "Author Name"
        config.project.language = "en"

        path = _generate_epub_metadata(config)
        try:
            content = path.read_text(encoding="utf-8")
            assert '<?xml version="1.0"' in content
            assert "<dc:title>My Book</dc:title>" in content
            assert "<dc:creator>Author Name</dc:creator>" in content
            assert "<dc:language>en</dc:language>" in content
            assert 'xmlns:dc="http://purl.org/dc/elements/1.1/"' in content
        finally:
            path.unlink(missing_ok=True)

    def test_user_template_overrides_packaged(self, tmp_path: Path) -> None:
        """A user-provided epub-metadata.xml overrides the packaged one."""
        config = _make_config(tmp_path)
        config.project.title = "Original"
        config.project.author = "Original Author"
        config.project.language = "es"

        user_dir = tmp_path / config.templates.dir
        user_dir.mkdir(parents=True)
        (user_dir / "epub-metadata.xml").write_text(
            '<?xml version="1.0"?>'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            "<dc:title>CUSTOM {{ project.title | e }}</dc:title>"
            "</metadata>"
        )

        path = _generate_epub_metadata(config)
        try:
            content = path.read_text(encoding="utf-8")
            assert "<dc:title>CUSTOM Original</dc:title>" in content
        finally:
            path.unlink(missing_ok=True)


class TestLatexTemplateResolution:
    """Tests for the _resolve_latex_template_path function."""

    def test_config_pdf_template_has_priority(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        custom = tmp_path / "my-template.tex"
        custom.write_text("% custom")
        config.pdf.template = "my-template.tex"

        result = _resolve_latex_template_path(config)
        assert result is not None
        assert result.name == "my-template.tex"

    def test_config_pdf_template_missing_file(self, tmp_path: Path) -> None:
        """When config.pdf.template points to missing file, falls back to packaged."""
        config = _make_config(tmp_path)
        config.pdf.template = "nonexistent.tex"

        result = _resolve_latex_template_path(config)
        assert result is not None
        assert "latex-template.tex" in str(result)

    def test_user_templates_dir_has_priority_over_packaged(
        self, tmp_path: Path
    ) -> None:
        config = _make_config(tmp_path)
        user_dir = tmp_path / config.templates.dir
        user_dir.mkdir(parents=True)
        (user_dir / "latex-template.tex").write_text("% user template")

        result = _resolve_latex_template_path(config)
        assert result is not None
        assert "latex-template.tex" in str(result)

    def test_falls_back_to_packaged(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        result = _resolve_latex_template_path(config)
        assert result is not None
        assert "latex-template.tex" in str(result)

    def test_config_pdf_template_none(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        config.pdf.template = None
        result = _resolve_latex_template_path(config)
        assert result is not None


class TestHtmlConversionWithTemplates:
    """Integration tests for HTML conversion with Jinja2 templates."""

    def test_html_conversion_uses_rendered_template(self, tmp_path: Path) -> None:
        """The HTML conversion passes a rendered template to Pandoc."""
        config = _make_config(tmp_path, formats=["html"])
        source = _make_source_file("content/index.md")
        source.frontmatter = {"title": "Welcome"}

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_text",
                return_value="<html>OK</html>",
            ) as mock_convert,
        ):
            convert(source, config, "# Hello\n")

        extra_args = mock_convert.call_args[1]["extra_args"]
        template_arg = next(a for a in extra_args if a.startswith("--template="))
        template_path = Path(template_arg.split("=", 1)[1])

        assert not template_path.exists()

    def test_html_conversion_with_all_documents(self, tmp_path: Path) -> None:
        """Sidebar is populated when all_documents is provided."""
        config = _make_config(tmp_path, formats=["html"])
        source = _make_source_file("content/index.md")
        source.frontmatter = {"title": "Home"}

        all_docs = [
            SourceFile(
                path=Path("content/index.md"),
                format="md",
                frontmatter={"title": "Home"},
            ),
            SourceFile(
                path=Path("content/about.md"),
                format="md",
                frontmatter={"title": "About Us"},
            ),
        ]

        captured_template: list[str] = []

        def _capture_template(text, to, format, extra_args):
            template_arg = next(a for a in extra_args if a.startswith("--template="))
            tp = Path(template_arg.split("=", 1)[1])
            captured_template.append(tp.read_text(encoding="utf-8"))
            return "<html>OK</html>"

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_text",
                side_effect=_capture_template,
            ),
        ):
            convert(source, config, "# Hello\n", all_documents=all_docs)

        assert len(captured_template) == 1
        assert "About Us" in captured_template[0]
        assert "Home" in captured_template[0]

    def test_user_base_html_overrides_packaged(self, tmp_path: Path) -> None:
        """A user-provided base.html is used instead of the packaged one."""
        config = _make_config(tmp_path, formats=["html"])
        source = _make_source_file("content/index.md")

        user_dir = tmp_path / config.templates.dir
        user_dir.mkdir(parents=True)
        (user_dir / "base.html").write_text(
            "<html><body>CUSTOM SITE {% raw %}$body${% endraw %}</body></html>"
        )

        captured_template: list[str] = []

        def _capture_template(text, to, format, extra_args):
            template_arg = next(a for a in extra_args if a.startswith("--template="))
            tp = Path(template_arg.split("=", 1)[1])
            captured_template.append(tp.read_text(encoding="utf-8"))
            return "<html>OK</html>"

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_text",
                side_effect=_capture_template,
            ),
        ):
            convert(source, config, "# Hello\n")

        assert len(captured_template) == 1
        assert "CUSTOM SITE" in captured_template[0]
        assert "$body$" in captured_template[0]


class TestPdfMathFont:
    """Tests for the math_font config field and its usage in PDF conversion."""

    def test_math_font_default(self) -> None:
        """PdfSection.math_font defaults to 'Latin Modern Math'."""
        from documentos.config import PdfSection

        section = PdfSection()
        assert section.math_font == "Latin Modern Math"

    def test_math_font_from_yaml(self, tmp_path: Path) -> None:
        """math_font is parsed from config.yml."""
        from documentos.config import load_config

        config_path = tmp_path / "config.yml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "content").mkdir()
        (tmp_path / "data").mkdir()
        (tmp_path / "templates").mkdir()

        config_path.write_text(
            "project:\n  title: Test\npdf:\n  math_font: STIX Two Math\n",
            encoding="utf-8",
        )

        cfg = load_config(config_path)
        assert cfg.pdf.math_font == "STIX Two Math"

    def test_math_font_passed_to_pandoc(self, tmp_path: Path) -> None:
        """The math_font value is passed as --variable=mathfont to Pandoc."""
        config = _make_config(tmp_path, formats=["pdf"])
        config.pdf.math_font = "XITS Math"
        source = _make_source_file("content/doc.md")

        with (
            patch(
                "documentos.build.converter.pypandoc.get_pandoc_version",
                return_value="3.1.2",
            ),
            patch(
                "documentos.build.converter.pypandoc.convert_text",
                return_value=r"\documentclass{article}\begin{document}T\end{document}",
            ) as mock_convert,
            patch(
                "documentos.build.converter.shutil.which",
                return_value="/usr/bin/latexmk",
            ),
            patch(
                "documentos.build.converter.subprocess.run",
            ),
        ):
            convert(source, config, "# Test\n")

        extra_args = mock_convert.call_args[1]["extra_args"]
        assert any("--variable=mathfont=XITS Math" in a for a in extra_args)

    def test_math_font_in_init_config(self, tmp_path: Path) -> None:
        """init_config writes math_font with default value."""
        from documentos.config import init_config

        config_path = tmp_path / "config.yml"
        init_config(config_path)

        content = config_path.read_text(encoding="utf-8")
        assert "math_font" in content
        assert "Latin Modern Math" in content
