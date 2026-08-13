"""Unit tests for the CLI module."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from documentos.build.collector import SourceFile
from documentos.build.converter import ConvertedFile
from documentos.cli import (
    _apply_file_filter,
    _normalise_path,
    _resolve_formats,
    main,
)
from documentos.config import ProjectConfig


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _init_project(project_dir: Path, runner: CliRunner) -> None:
    """Helper: run ``documentos init`` inside *project_dir*."""
    cwd = os.getcwd()
    try:
        os.chdir(project_dir)
        r = runner.invoke(main, ["init"])
        assert r.exit_code == 0, f"init failed: {r.output}"
    finally:
        os.chdir(cwd)


def _make_config(root: Path) -> ProjectConfig:
    """Create a minimal ProjectConfig for testing."""
    return ProjectConfig(
        root=root,
    )


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


class TestInit:
    def test_creates_directory_structure(self, runner: CliRunner, tmp_path: Path):
        target = tmp_path / "mi-proyecto"
        result = runner.invoke(main, ["init", str(target)])
        assert result.exit_code == 0

        for dirname in ("content", "data", "templates", "output"):
            assert (target / dirname).is_dir()

    def test_creates_structure_in_current_dir(self, runner: CliRunner, tmp_path: Path):
        cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(main, ["init"])
            assert result.exit_code == 0
            for dirname in ("content", "data", "templates", "output"):
                assert (tmp_path / dirname).is_dir()
        finally:
            os.chdir(cwd)

    def test_generates_config_yml(self, runner: CliRunner, tmp_path: Path):
        target = tmp_path / "mi-proyecto"
        runner.invoke(main, ["init", str(target)])

        config_path = target / "config.yml"
        assert config_path.is_file()

        with config_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        assert data["project"]["title"] == "Nombre del Proyecto"
        assert data["project"]["author"] == "Autor"
        assert data["project"]["language"] == "es"

    def test_generates_content_index_md(self, runner: CliRunner, tmp_path: Path):
        target = tmp_path / "mi-proyecto"
        runner.invoke(main, ["init", str(target)])

        index_path = target / "content" / "index.md"
        assert index_path.is_file()

        content = index_path.read_text(encoding="utf-8")
        assert "title:" in content
        assert "author:" in content
        assert "date:" in content
        assert "Bienvenido" in content

    def test_success_message_references_build_and_serve(
        self, runner: CliRunner, tmp_path: Path
    ):
        target = tmp_path / "mi-proyecto"
        result = runner.invoke(main, ["init", str(target)])
        assert result.exit_code == 0
        assert "Proyecto creado exitosamente" in result.output
        assert "documentos build" in result.output
        assert "documentos serve" in result.output

    def test_existing_path_prompts_before_overwrite(
        self, runner: CliRunner, tmp_path: Path
    ):
        target = tmp_path / "mi-proyecto"
        target.mkdir()
        (target / "config.yml").write_text('project:\n  title: "Existente"\n')

        result = runner.invoke(main, ["init", str(target)], input="n\n")
        assert result.exit_code != 0
        assert "ya contiene un proyecto" in result.output.lower()

    def test_existing_path_overwrite_confirmed(self, runner: CliRunner, tmp_path: Path):
        target = tmp_path / "mi-proyecto"
        target.mkdir()
        (target / "config.yml").write_text('project:\n  title: "Existente"\n')

        result = runner.invoke(main, ["init", str(target)], input="y\n")
        assert result.exit_code == 0

        with (target / "config.yml").open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        assert data["project"]["title"] == "Nombre del Proyecto"


# ---------------------------------------------------------------------------
# build — unit tests for helpers
# ---------------------------------------------------------------------------


class TestBuildHelpers:
    """Tests for internal build pipeline helper functions."""

    def test_resolve_formats_cli_flag_takes_precedence(self, tmp_path: Path):
        """--format flag overrides everything."""
        cfg = _make_config(tmp_path)
        cfg.output.formats = ["html", "pdf", "epub"]
        source = SourceFile(
            path=Path("content/doc.md"),
            format="md",
            frontmatter={"formats": ["pdf"], "skip_pdf": True},
        )
        result = _resolve_formats(source, cfg, "html")
        assert result == ["html"]

    def test_resolve_formats_frontmatter_formats(self, tmp_path: Path):
        """frontmatter 'formats' field overrides config."""
        cfg = _make_config(tmp_path)
        cfg.output.formats = ["html", "pdf", "epub"]
        source = SourceFile(
            path=Path("content/doc.md"),
            format="md",
            frontmatter={"formats": ["html"]},
        )
        result = _resolve_formats(source, cfg, None)
        assert result == ["html"]

    def test_resolve_formats_skip_pdf(self, tmp_path: Path):
        """skip_pdf: true removes pdf from formats."""
        cfg = _make_config(tmp_path)
        cfg.output.formats = ["html", "pdf", "epub"]
        source = SourceFile(
            path=Path("content/doc.md"),
            format="md",
            frontmatter={"skip_pdf": True},
        )
        result = _resolve_formats(source, cfg, None)
        assert result == ["html", "epub"]

    def test_resolve_formats_default(self, tmp_path: Path):
        """No frontmatter overrides → use config formats."""
        cfg = _make_config(tmp_path)
        cfg.output.formats = ["html", "pdf"]
        source = SourceFile(
            path=Path("content/doc.md"),
            format="md",
            frontmatter={"title": "Doc"},
        )
        result = _resolve_formats(source, cfg, None)
        assert result == ["html", "pdf"]

    def test_resolve_formats_skip_pdf_no_pdf_in_config(self, tmp_path: Path):
        """skip_pdf when pdf is not in config → no change."""
        cfg = _make_config(tmp_path)
        cfg.output.formats = ["html", "epub"]
        source = SourceFile(
            path=Path("content/doc.md"),
            format="md",
            frontmatter={"skip_pdf": True},
        )
        result = _resolve_formats(source, cfg, None)
        assert result == ["html", "epub"]

    def test_apply_file_filter_no_filter(self, tmp_path: Path):
        """No --file flag returns all sources."""
        sources = [
            SourceFile(path=Path("content/a.md"), format="md"),
            SourceFile(path=Path("content/b.md"), format="md"),
        ]
        result = _apply_file_filter(sources, None)
        assert len(result) == 2

    def test_apply_file_filter_matches_relative_path(self, tmp_path: Path):
        """--file flag matches relative path from content/."""
        sources = [
            SourceFile(path=Path("content/a.md"), format="md"),
            SourceFile(path=Path("content/guias/b.md"), format="md"),
        ]
        result = _apply_file_filter(sources, "guias/b.md")
        assert len(result) == 1
        assert result[0].path == Path("content/guias/b.md")

    def test_apply_file_filter_no_match(self, tmp_path: Path):
        """Non-matching --file returns empty list."""
        sources = [
            SourceFile(path=Path("content/a.md"), format="md"),
        ]
        result = _apply_file_filter(sources, "nonexistent.md")
        assert len(result) == 0

    def test_normalise_path_strips_content_prefix(self):
        """content prefix is stripped."""
        assert _normalise_path(Path("content/a.md")) == "a.md"
        assert _normalise_path(Path("content/guias/b.md")) == "guias/b.md"

    def test_normalise_path_no_prefix(self):
        """Paths without content prefix returned as-is."""
        assert _normalise_path(Path("other/a.md")) == "other/a.md"


# ---------------------------------------------------------------------------
# build — CLI integration tests
# ---------------------------------------------------------------------------


_SUCCESS_HTML = ConvertedFile(
    source=Path("content/index.md"),
    format="html",
    output=Path("output/html/index.html"),
    success=True,
)
_SUCCESS_PDF = ConvertedFile(
    source=Path("content/index.md"),
    format="pdf",
    output=Path("output/pdf/index.pdf"),
    success=True,
)


class TestBuild:
    def test_build_without_config_shows_error(self, runner: CliRunner, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        cwd = os.getcwd()
        try:
            os.chdir(empty)
            result = runner.invoke(main, ["build"])
            assert result.exit_code != 0
            assert "No se encontró config.yml" in result.output
        finally:
            os.chdir(cwd)

    def test_build_with_config_error_from_validation(
        self, runner: CliRunner, tmp_path: Path
    ):
        """build shows error when config.yml exists but required dirs are missing."""
        proj = tmp_path / "proyecto"
        proj.mkdir()
        config_path = proj / "config.yml"
        config_path.write_text('project:\n  title: "Un proyecto"\n', encoding="utf-8")

        cwd = os.getcwd()
        try:
            os.chdir(proj)
            result = runner.invoke(main, ["build"])
            assert result.exit_code != 0
            assert "Missing required director" in result.output
        finally:
            os.chdir(cwd)

    @patch("documentos.cli.pypandoc.get_pandoc_version", return_value="3.1")
    @patch("documentos.cli.convert", return_value=[_SUCCESS_HTML])
    @patch("documentos.cli.copy_assets", return_value=[])
    @patch("documentos.cli.generate_index", return_value=Path("/fake/index.html"))
    def test_build_full_pipeline(
        self,
        mock_index,
        mock_assets,
        mock_convert,
        mock_pandoc,
        runner: CliRunner,
        tmp_path: Path,
    ):
        """Full pipeline runs successfully with all steps."""
        proj = tmp_path / "proyecto"
        proj.mkdir()
        for d in ("content", "data", "templates"):
            (proj / d).mkdir()
        _init_project(proj, runner)

        cwd = os.getcwd()
        try:
            os.chdir(proj)
            result = runner.invoke(main, ["build"])
            assert result.exit_code == 0
            assert "Cargando configuración... OK" in result.output
            assert "Recolectando archivos fuente" in result.output
            assert "Cargando archivos de datos" in result.output
            assert "Ejecutando consultas" in result.output
            assert "Convirtiendo documentos" in result.output
            assert "Copiando activos estáticos" in result.output
            assert "Generando índices" in result.output
            assert "Build completado" in result.output
            assert "Salida disponible en output/" in result.output
        finally:
            os.chdir(cwd)

    @patch("documentos.cli.pypandoc.get_pandoc_version", return_value="3.1")
    @patch("documentos.cli.convert", return_value=[_SUCCESS_HTML])
    @patch("documentos.cli.copy_assets", return_value=[])
    @patch("documentos.cli.generate_index", return_value=Path("/fake/index.html"))
    def test_build_shows_file_status(
        self,
        mock_index,
        mock_assets,
        mock_convert,
        mock_pandoc,
        runner: CliRunner,
        tmp_path: Path,
    ):
        """Build output shows per-file conversion status with ✓."""
        proj = tmp_path / "proyecto"
        proj.mkdir()
        for d in ("content", "data", "templates"):
            (proj / d).mkdir()
        _init_project(proj, runner)

        cwd = os.getcwd()
        try:
            os.chdir(proj)
            result = runner.invoke(main, ["build"])
            assert "✓" in result.output
            assert "content/index.md" in result.output
        finally:
            os.chdir(cwd)

    @patch("documentos.cli.pypandoc.get_pandoc_version", return_value="3.1")
    @patch("documentos.cli.convert", return_value=[_SUCCESS_HTML])
    @patch("documentos.cli.copy_assets", return_value=[])
    @patch("documentos.cli.generate_index", return_value=Path("/fake/index.html"))
    def test_build_summary_shows_format_counts(
        self,
        mock_index,
        mock_assets,
        mock_convert,
        mock_pandoc,
        runner: CliRunner,
        tmp_path: Path,
    ):
        """Build summary includes format count."""
        proj = tmp_path / "proyecto"
        proj.mkdir()
        for d in ("content", "data", "templates"):
            (proj / d).mkdir()
        _init_project(proj, runner)

        cwd = os.getcwd()
        try:
            os.chdir(proj)
            result = runner.invoke(main, ["build"])
            assert "Formatos generados:" in result.output
            assert "html" in result.output
            assert "Advertencias:" in result.output
            assert "Errores:" in result.output
        finally:
            os.chdir(cwd)

    @patch("documentos.cli.pypandoc.get_pandoc_version", return_value="3.1")
    @patch("documentos.cli.convert", return_value=[_SUCCESS_HTML, _SUCCESS_PDF])
    @patch("documentos.cli.copy_assets", return_value=[])
    @patch("documentos.cli.generate_index", return_value=Path("/fake/index.html"))
    def test_build_summary_multiple_formats(
        self,
        mock_index,
        mock_assets,
        mock_convert,
        mock_pandoc,
        runner: CliRunner,
        tmp_path: Path,
    ):
        """Build summary shows multiple formats with counts."""
        proj = tmp_path / "proyecto"
        proj.mkdir()
        for d in ("content", "data", "templates"):
            (proj / d).mkdir()
        _init_project(proj, runner)

        cwd = os.getcwd()
        try:
            os.chdir(proj)
            result = runner.invoke(main, ["build"])
            assert "html (1)" in result.output
            assert "pdf (1)" in result.output
        finally:
            os.chdir(cwd)

    @patch("documentos.cli.pypandoc.get_pandoc_version", return_value="3.1")
    @patch("documentos.cli.convert", return_value=[_SUCCESS_HTML])
    @patch("documentos.cli.copy_assets", return_value=[])
    @patch("documentos.cli.generate_index", return_value=Path("/fake/index.html"))
    def test_build_no_content_files_shows_message(
        self,
        mock_index,
        mock_assets,
        mock_convert,
        mock_pandoc,
        runner: CliRunner,
        tmp_path: Path,
    ):
        """Empty content dir shows appropriate message."""
        proj = tmp_path / "proyecto"
        proj.mkdir()
        for d in ("content", "data", "templates"):
            (proj / d).mkdir()
        _init_project(proj, runner)
        (proj / "content" / "index.md").unlink()

        cwd = os.getcwd()
        try:
            os.chdir(proj)
            result = runner.invoke(main, ["build"])
            assert result.exit_code == 0
            assert "no se encontraron archivos fuente" in result.output.lower()
            assert "Build pipeline no implementado" not in result.output
        finally:
            os.chdir(cwd)

    @patch("documentos.cli.pypandoc.get_pandoc_version", return_value="3.1")
    @patch("documentos.cli.convert", return_value=[_SUCCESS_HTML])
    @patch("documentos.cli.copy_assets", return_value=[])
    @patch("documentos.cli.generate_index", return_value=Path("/fake/index.html"))
    def test_build_format_flag(
        self,
        mock_index,
        mock_assets,
        mock_convert,
        mock_pandoc,
        runner: CliRunner,
        tmp_path: Path,
    ):
        """--format html generates only HTML."""
        proj = tmp_path / "proyecto"
        proj.mkdir()
        for d in ("content", "data", "templates"):
            (proj / d).mkdir()
        _init_project(proj, runner)

        cwd = os.getcwd()
        try:
            os.chdir(proj)
            result = runner.invoke(main, ["build", "--format", "html"])
            assert result.exit_code == 0
            assert "Convirtiendo documentos" in result.output
        finally:
            os.chdir(cwd)

    @patch("documentos.cli.pypandoc.get_pandoc_version", return_value="3.1")
    @patch("documentos.cli.convert", return_value=[_SUCCESS_HTML])
    @patch("documentos.cli.copy_assets", return_value=[])
    @patch("documentos.cli.generate_index", return_value=Path("/fake/index.html"))
    def test_build_file_flag(
        self,
        mock_index,
        mock_assets,
        mock_convert,
        mock_pandoc,
        runner: CliRunner,
        tmp_path: Path,
    ):
        """--file flag filters to one document."""
        proj = tmp_path / "proyecto"
        proj.mkdir()
        for d in ("content", "data", "templates"):
            (proj / d).mkdir()
        _init_project(proj, runner)
        # Add a second file to verify filtering
        (proj / "content" / "other.md").write_text("# Other")

        cwd = os.getcwd()
        try:
            os.chdir(proj)
            result = runner.invoke(main, ["build", "--file", "index.md"])
            assert result.exit_code == 0
            # Only one file should be converted
            assert mock_convert.call_count == 1
        finally:
            os.chdir(cwd)

    @patch("documentos.cli.pypandoc.get_pandoc_version", return_value="3.1")
    @patch("documentos.cli.convert", return_value=[_SUCCESS_HTML])
    @patch("documentos.cli.copy_assets", return_value=[])
    @patch("documentos.cli.generate_index", return_value=Path("/fake/index.html"))
    def test_build_format_and_file_flags(
        self,
        mock_index,
        mock_assets,
        mock_convert,
        mock_pandoc,
        runner: CliRunner,
        tmp_path: Path,
    ):
        """Both --format and --file flags together."""
        proj = tmp_path / "proyecto"
        proj.mkdir()
        for d in ("content", "data", "templates"):
            (proj / d).mkdir()
        _init_project(proj, runner)

        cwd = os.getcwd()
        try:
            os.chdir(proj)
            result = runner.invoke(
                main, ["build", "--format", "html", "--file", "index.md"]
            )
            assert result.exit_code == 0
            assert mock_convert.call_count == 1
        finally:
            os.chdir(cwd)

    @patch("documentos.cli.pypandoc.get_pandoc_version", return_value="3.1")
    @patch("documentos.cli.convert", return_value=[_SUCCESS_HTML])
    @patch("documentos.cli.copy_assets", return_value=[])
    @patch("documentos.cli.generate_index", return_value=Path("/fake/index.html"))
    def test_build_help_shows_format_and_file(
        self,
        mock_index,
        mock_assets,
        mock_convert,
        mock_pandoc,
        runner: CliRunner,
    ):
        """build --help shows the new options."""
        result = runner.invoke(main, ["build", "--help"])
        assert result.exit_code == 0
        assert "--format" in result.output
        assert "--file" in result.output

    @patch("documentos.cli.pypandoc.get_pandoc_version")
    def test_build_pandoc_not_installed(
        self,
        mock_pandoc,
        runner: CliRunner,
        tmp_path: Path,
    ):
        """Pandoc not installed → error message and non-zero exit."""
        mock_pandoc.side_effect = OSError("Pandoc not found")
        proj = tmp_path / "proyecto"
        proj.mkdir()
        for d in ("content", "data", "templates"):
            (proj / d).mkdir()
        _init_project(proj, runner)

        cwd = os.getcwd()
        try:
            os.chdir(proj)
            result = runner.invoke(main, ["build"])
            assert result.exit_code != 0
            assert "Pandoc no está instalado" in result.output
        finally:
            os.chdir(cwd)

    @patch("documentos.cli.pypandoc.get_pandoc_version", return_value="3.1")
    @patch("documentos.cli.copy_assets", return_value=[])
    @patch("documentos.cli.generate_index", return_value=Path("/fake/index.html"))
    def test_build_conversion_warning(
        self,
        mock_index,
        mock_assets,
        mock_pandoc,
        runner: CliRunner,
        tmp_path: Path,
    ):
        """Failed conversion shows as warning in output."""
        failed = ConvertedFile(
            source=Path("content/index.md"),
            format="pdf",
            output=Path("output/pdf/index.pdf"),
            success=False,
            error="latexmk not installed — PDF generation skipped",
        )

        with patch("documentos.cli.convert", return_value=[failed]):
            proj = tmp_path / "proyecto"
            proj.mkdir()
            for d in ("content", "data", "templates"):
                (proj / d).mkdir()
            _init_project(proj, runner)

            cwd = os.getcwd()
            try:
                os.chdir(proj)
                result = runner.invoke(main, ["build"])
                assert result.exit_code == 0
                assert "⚠" in result.output
                assert "latexmk not installed" in result.output
                assert "Advertencias: 1" in result.output
            finally:
                os.chdir(cwd)

    @patch("documentos.cli.pypandoc.get_pandoc_version", return_value="3.1")
    @patch("documentos.cli.convert")
    @patch("documentos.cli.copy_assets", return_value=[])
    @patch("documentos.cli.generate_index", return_value=Path("/fake/index.html"))
    def test_build_conversion_error(
        self,
        mock_index,
        mock_assets,
        mock_convert,
        mock_pandoc,
        runner: CliRunner,
        tmp_path: Path,
    ):
        """Conversion RuntimeError shows as error in output."""
        mock_convert.side_effect = RuntimeError("Conversion failed")

        proj = tmp_path / "proyecto"
        proj.mkdir()
        for d in ("content", "data", "templates"):
            (proj / d).mkdir()
        _init_project(proj, runner)

        cwd = os.getcwd()
        try:
            os.chdir(proj)
            result = runner.invoke(main, ["build"])
            assert result.exit_code == 0
            assert "✗" in result.output
            assert "Conversion failed" in result.output
            assert "Errores: 1" in result.output
        finally:
            os.chdir(cwd)

    @patch("documentos.cli.pypandoc.get_pandoc_version", return_value="3.1")
    @patch("documentos.cli.convert", return_value=[_SUCCESS_HTML])
    @patch("documentos.cli.copy_assets", return_value=[])
    @patch("documentos.cli.generate_index", return_value=Path("/fake/index.html"))
    def test_build_elapsed_time_in_summary(
        self,
        mock_index,
        mock_assets,
        mock_convert,
        mock_pandoc,
        runner: CliRunner,
        tmp_path: Path,
    ):
        """Build summary includes elapsed time."""
        proj = tmp_path / "proyecto"
        proj.mkdir()
        for d in ("content", "data", "templates"):
            (proj / d).mkdir()
        _init_project(proj, runner)

        cwd = os.getcwd()
        try:
            os.chdir(proj)
            result = runner.invoke(main, ["build"])
            assert "Build completado en" in result.output
            assert "s" in result.output
        finally:
            os.chdir(cwd)

    @patch("documentos.cli.pypandoc.get_pandoc_version", return_value="3.1")
    @patch("documentos.cli.convert", return_value=[_SUCCESS_HTML])
    @patch("documentos.cli.copy_assets", return_value=[])
    @patch("documentos.cli.generate_index", side_effect=OSError("disk full"))
    def test_build_index_generation_error(
        self,
        mock_index,
        mock_assets,
        mock_convert,
        mock_pandoc,
        runner: CliRunner,
        tmp_path: Path,
    ):
        """Index generation failure is reported as warning, not fatal."""
        proj = tmp_path / "proyecto"
        proj.mkdir()
        for d in ("content", "data", "templates"):
            (proj / d).mkdir()
        _init_project(proj, runner)

        cwd = os.getcwd()
        try:
            os.chdir(proj)
            result = runner.invoke(main, ["build"])
            assert result.exit_code == 0
            assert "Advertencias: 1" in result.output
            assert "index" in result.output.lower()
        finally:
            os.chdir(cwd)

    @patch("documentos.cli.pypandoc.get_pandoc_version", return_value="3.1")
    @patch("documentos.cli.convert", return_value=[_SUCCESS_HTML])
    @patch("documentos.cli.copy_assets", side_effect=OSError("read-only fs"))
    @patch("documentos.cli.generate_index", return_value=Path("/fake/index.html"))
    def test_build_assets_error_is_warning(
        self,
        mock_index,
        mock_assets,
        mock_convert,
        mock_pandoc,
        runner: CliRunner,
        tmp_path: Path,
    ):
        """Assets copy failure is reported as warning."""
        proj = tmp_path / "proyecto"
        proj.mkdir()
        for d in ("content", "data", "templates"):
            (proj / d).mkdir()
        _init_project(proj, runner)

        cwd = os.getcwd()
        try:
            os.chdir(proj)
            result = runner.invoke(main, ["build"])
            assert result.exit_code == 0
            assert "Advertencias: 1" in result.output
            assert "copy_assets" in result.output
        finally:
            os.chdir(cwd)


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


class TestServe:
    def test_serve_shows_placeholder_message(self, runner: CliRunner):
        result = runner.invoke(main, ["serve"])
        assert result.exit_code == 0
        assert "Servidor no implementado" in result.output
        assert "Fase 3" in result.output


# ---------------------------------------------------------------------------
# Legacy / smoke tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# init — assets generation (TK-016)
# ---------------------------------------------------------------------------


class TestInitAssets:
    """Tests that init generates default CSS and JavaScript assets."""

    def test_init_creates_css(self, runner: CliRunner, tmp_path: Path):
        target = tmp_path / "proyecto"
        result = runner.invoke(main, ["init", str(target)])
        assert result.exit_code == 0

        css_path = target / "templates" / "assets" / "css" / "style.css"
        assert css_path.is_file()

        content = css_path.read_text(encoding="utf-8")
        assert "box-sizing" in content
        assert "font-family" in content

    def test_init_creates_js(self, runner: CliRunner, tmp_path: Path):
        target = tmp_path / "proyecto"
        result = runner.invoke(main, ["init", str(target)])
        assert result.exit_code == 0

        js_path = target / "templates" / "assets" / "js" / "mathjax-config.js"
        assert js_path.is_file()

        content = js_path.read_text(encoding="utf-8")
        assert "MathJax" in content
        assert "inlineMath" in content

    def test_init_assets_writable(self, runner: CliRunner, tmp_path: Path):
        """Assets generated by init are writable (user can customize)."""
        target = tmp_path / "proyecto"
        runner.invoke(main, ["init", str(target)])

        css_path = target / "templates" / "assets" / "css" / "style.css"
        css_path.write_text("/* custom */", encoding="utf-8")
        assert css_path.read_text(encoding="utf-8") == "/* custom */"


# ---------------------------------------------------------------------------
# Legacy / smoke tests
# ---------------------------------------------------------------------------


class TestLegacy:
    def test_version_is_correct(self):
        from documentos import __version__

        assert __version__ == "0.1.0"

    def test_cli_module_exposes_main(self):
        from documentos import cli as cli_module

        assert hasattr(cli_module, "main")

    def test_cli_help(self, runner: CliRunner):
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "init" in result.output
        assert "build" in result.output
        assert "serve" in result.output
