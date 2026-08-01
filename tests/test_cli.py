"""Unit tests for the CLI module."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from documentos.cli import main


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

    def test_creates_structure_in_current_dir(
        self, runner: CliRunner, tmp_path: Path
    ):
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
        (target / "config.yml").write_text("project:\n  title: \"Existente\"\n")

        result = runner.invoke(main, ["init", str(target)], input="n\n")
        assert result.exit_code != 0
        assert "ya contiene un proyecto" in result.output.lower()

    def test_existing_path_overwrite_confirmed(
        self, runner: CliRunner, tmp_path: Path
    ):
        target = tmp_path / "mi-proyecto"
        target.mkdir()
        (target / "config.yml").write_text("project:\n  title: \"Existente\"\n")

        result = runner.invoke(main, ["init", str(target)], input="y\n")
        assert result.exit_code == 0

        with (target / "config.yml").open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        assert data["project"]["title"] == "Nombre del Proyecto"


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


class TestBuild:
    def test_build_enumerates_files(self, runner: CliRunner, tmp_path: Path):
        proj = tmp_path / "proyecto"
        proj.mkdir()
        for d in ("content", "data", "templates"):
            (proj / d).mkdir()

        _init_project(proj, runner)

        (proj / "content" / "a.md").write_text("---\ntitle: A\n---\n# A")
        (proj / "content" / "b.adoc").write_text("= B")

        cwd = os.getcwd()
        try:
            os.chdir(proj)
            result = runner.invoke(main, ["build"])
            assert result.exit_code == 0
            assert "content/a.md [md]" in result.output
            assert "content/b.adoc [adoc]" in result.output
        finally:
            os.chdir(cwd)

    def test_build_shows_pipeline_message(self, runner: CliRunner, tmp_path: Path):
        proj = tmp_path / "proyecto"
        proj.mkdir()
        for d in ("content", "data", "templates"):
            (proj / d).mkdir()
        _init_project(proj, runner)
        (proj / "content" / "doc.md").write_text("# Doc")

        cwd = os.getcwd()
        try:
            os.chdir(proj)
            result = runner.invoke(main, ["build"])
            assert "Build pipeline no implementado" in result.output
        finally:
            os.chdir(cwd)

    def test_build_without_config_shows_error(
        self, runner: CliRunner, tmp_path: Path
    ):
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

    def test_build_no_content_files_shows_empty_message(
        self, runner: CliRunner, tmp_path: Path
    ):
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
            assert "Build pipeline no implementado" in result.output
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
