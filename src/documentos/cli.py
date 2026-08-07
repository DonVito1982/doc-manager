"""CLI with Click — entry point for the ``documentos`` command."""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path

import click
import pypandoc

from documentos.build.assets import copy_assets
from documentos.build.collector import SourceFile, collect
from documentos.build.converter import convert
from documentos.build.indexer import generate_index
from documentos.build.preprocessor import (
    DataContext,
    execute_db_queries,
    load_data_files,
    preprocess,
)
from documentos.config import ConfigError, ProjectConfig, init_config, load_config

# ---------------------------------------------------------------------------
# Content template for ``init``
# ---------------------------------------------------------------------------

INDEX_MD_CONTENT = """\
---
title: "Bienvenido a la Documentación"
author: "Autor"
date: {date}
---

# Bienvenido a la Documentación

¡Tu proyecto de documentación ha sido creado exitosamente!

## Siguientes pasos

- Agrega tus documentos Markdown en el directorio `content/`.
- Ejecuta `documentos build` para construir la documentación.
- Ejecuta `documentos serve` para previsualizar el resultado.

Para más información, consulta la documentación del proyecto.
"""

# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group()
def main():
    """Gestor de documentos para firmas de ingeniería."""


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@main.command()
@click.argument("ruta", required=False, default=".", type=click.Path())
def init(ruta: str):
    """Crea un nuevo proyecto de documentación."""
    project_path = Path(ruta).resolve()
    config_path = project_path / "config.yml"

    if config_path.exists():
        if not click.confirm(
            f"La ruta '{project_path}' ya contiene un proyecto. ¿Desea sobrescribirlo?",
            default=False,
        ):
            raise click.Abort()

    dirs = ["content", "data", "templates", "output"]
    for dirname in dirs:
        (project_path / dirname).mkdir(parents=True, exist_ok=True)

    init_config(config_path)

    index_path = project_path / "content" / "index.md"
    index_path.write_text(
        INDEX_MD_CONTENT.format(date=date.today().isoformat()),
        encoding="utf-8",
    )

    click.echo(f"\nProyecto creado exitosamente en '{project_path}'.")
    click.echo("Siguientes pasos:")
    click.echo("  1. Agrega tus documentos en content/")
    click.echo("  2. Ejecuta `documentos build` para construir la documentación.")
    click.echo("  3. Ejecuta `documentos serve` para previsualizar el resultado.\n")


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--format",
    "fmt_filter",
    type=click.Choice(["html", "pdf", "epub"]),
    help="Restringe la generación a un solo formato.",
)
@click.option(
    "--file",
    "file_filter",
    type=str,
    help="Restringe la generación a un solo archivo fuente "
    "(ruta relativa desde content/).",
)
def build(fmt_filter: str | None, file_filter: str | None):
    """Construye el proyecto de documentación."""
    config_path = Path("config.yml")
    if not config_path.is_file():
        raise click.ClickException(
            f"No se encontró config.yml en el directorio actual ({Path.cwd()}). "
            "Ejecute 'documentos init' para crear un nuevo proyecto."
        )

    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    start_time = time.monotonic()
    warnings: list[str] = []
    errors: list[str] = []

    # 1 ─ Check Pandoc availability -----------------------------------------
    try:
        click.echo("Cargando configuración... ", nl=False)
        pypandoc.get_pandoc_version()
        click.echo(click.style("OK", fg="green"))
    except OSError as exc:
        click.echo(click.style("ERROR", fg="red"))
        raise click.ClickException(
            "Pandoc no está instalado o no se encuentra en PATH. "
            "Instala Pandoc: https://pandoc.org/installing.html"
        ) from exc

    # 2 ─ Collect source files -----------------------------------------------
    click.echo("Recolectando archivos fuente... ", nl=False)
    all_sources = collect(cfg)
    click.echo(f"{len(all_sources)} archivos encontrados")

    # 3 ─ Filter by --file --------------------------------------------------
    sources = _apply_file_filter(all_sources, file_filter)

    if not sources:
        click.echo("  (no se encontraron archivos fuente)")
        _print_build_summary(time.monotonic() - start_time, [], [], warnings, errors)
        return

    # 4 ─ Load data files ---------------------------------------------------
    click.echo("Cargando archivos de datos... ", nl=False)
    try:
        data = load_data_files(cfg)
        data_count = len(data)
        click.echo(f"{data_count} archivos cargados")
    except Exception as exc:
        data_count = 0
        data = {}
        click.echo(click.style(f"error: {exc}", fg="yellow"))

    # 5 ─ Execute DB queries ------------------------------------------------
    click.echo("Ejecutando consultas de base de datos... ", nl=False)
    try:
        db = execute_db_queries(cfg)
        db_count = len(db)
        click.echo(f"{db_count} consultas ejecutadas")
    except Exception as exc:
        db_count = 0
        db = {}
        click.echo(click.style(f"error: {exc}", fg="yellow"))

    # 6 ─ Build DataContext -------------------------------------------------
    project_meta = {
        "title": cfg.project.title,
        "author": cfg.project.author,
        "language": cfg.project.language,
    }
    context = DataContext(project=project_meta, data=data, db=db)

    # 7 ─ Preprocess & convert each file ------------------------------------
    all_results: list = []
    click.echo("Convirtiendo documentos...")

    for source in sources:
        try:
            preprocessed = preprocess(source, context)
        except Exception as exc:
            msg = f"  ✗ {source.path} → error de preprocesamiento: {exc}"
            click.echo(click.style(msg, fg="red"))
            errors.append(f"{source.path}: preprocesamiento fallido — {exc}")
            continue

        resolved_formats = _resolve_formats(source, cfg, fmt_filter)
        original_formats = cfg.output.formats

        try:
            cfg.output.formats = resolved_formats
            results = convert(source, cfg, preprocessed, all_sources)
        except RuntimeError as exc:
            msg = f"  ✗ {source.path} → error de conversión: {exc}"
            click.echo(click.style(msg, fg="red"))
            errors.append(f"{source.path}: {exc}")
            continue
        except Exception as exc:
            msg = f"  ✗ {source.path} → error inesperado: {exc}"
            click.echo(click.style(msg, fg="red"))
            errors.append(f"{source.path}: {exc}")
            continue
        finally:
            cfg.output.formats = original_formats

        all_results.extend(results)

        # Per-file status line
        fmt_labels = ", ".join(resolved_formats)
        failed = [r for r in results if not r.success]
        if failed:
            fail_fmts = ", ".join(r.format for r in failed)
            fail_reasons = "; ".join(r.error or "error desconocido" for r in failed)
            click.echo(
                click.style(
                    f"  ⚠ {source.path} → {fmt_labels}: {fail_fmts} omitidos "
                    f"({fail_reasons})",
                    fg="yellow",
                )
            )
            warnings.extend(f"{source.path} ({r.format}): {r.error}" for r in failed)
        else:
            click.echo(f"  {click.style('✓', fg='green')} {source.path} → {fmt_labels}")

    # 8 ─ Copy assets -------------------------------------------------------
    click.echo("Copiando activos estáticos... ", nl=False)
    try:
        copy_assets(cfg)
        click.echo(click.style("OK", fg="green"))
    except Exception as exc:
        click.echo(click.style(f"error: {exc}", fg="yellow"))
        warnings.append(f"copy_assets: {exc}")

    # 9 ─ Generate index ----------------------------------------------------
    click.echo("Generando índices... ", nl=False)
    try:
        generate_index(sources, cfg)
        click.echo(click.style("OK", fg="green"))
    except Exception as exc:
        click.echo(click.style(f"error: {exc}", fg="yellow"))
        warnings.append(f"index generation: {exc}")

    # 10 ─ Build summary ----------------------------------------------------
    elapsed = time.monotonic() - start_time
    _print_build_summary(elapsed, all_results, resolved_formats, warnings, errors)


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


@main.command()
def serve():
    """Servidor web (placeholder)."""
    click.echo("Servidor no implementado — disponible en la Fase 3")


# ---------------------------------------------------------------------------
# Internal — build helpers
# ---------------------------------------------------------------------------


def _resolve_formats(
    source: SourceFile,
    config: ProjectConfig,
    cli_format: str | None,
) -> list[str]:
    """Determine the output formats for a single source file.

    Resolution order:
    1. CLI ``--format`` flag (highest precedence).
    2. ``formats`` field in frontmatter.
    3. ``config.output.formats`` with optional ``skip_pdf``.

    Args:
        source: The source file being processed.
        config: The project configuration.
        cli_format: The ``--format`` value from the CLI, or ``None``.

    Returns:
        A list of output format strings (e.g. ``["html", "pdf"]``).
    """
    if cli_format:
        return [cli_format]

    fm = source.frontmatter
    if "formats" in fm:
        fm_formats = fm["formats"]
        if isinstance(fm_formats, list):
            return [str(f) for f in fm_formats]

    formats = list(config.output.formats)

    if fm.get("skip_pdf") and "pdf" in formats:
        formats.remove("pdf")

    return formats


def _apply_file_filter(
    sources: list[SourceFile],
    file_filter: str | None,
) -> list[SourceFile]:
    """Filter collected source files by the ``--file`` CLI option.

    The *file_filter* is matched against the last part of the source path
    (stripping the ``content/`` prefix).

    Args:
        sources: All collected source files.
        file_filter: Relative path from ``content/``, or ``None``.

    Returns:
        Filtered list of ``SourceFile`` instances.
    """
    if not file_filter:
        return list(sources)

    return [s for s in sources if _normalise_path(s.path) == file_filter]


def _normalise_path(path: Path) -> str:
    """Strip the ``content/`` prefix from *path* and return as POSIX string."""
    parts = path.parts
    if parts and parts[0] == "content":
        return str(Path(*parts[1:]).as_posix())
    return path.as_posix()


def _print_build_summary(
    elapsed: float,
    results: list,
    final_formats: list[str],
    warnings: list[str],
    errors: list[str],
) -> None:
    """Print the build summary with timing, counts, warnings, and errors."""
    click.echo()
    click.echo(click.style(f"Build completado en {elapsed:.1f}s", bold=True))

    # Format counts
    fmt_counts: dict[str, int] = {}
    for r in results:
        if r.success:
            fmt_counts[r.format] = fmt_counts.get(r.format, 0) + 1

    if fmt_counts:
        parts = ", ".join(
            f"{fmt} ({count})" for fmt, count in sorted(fmt_counts.items())
        )
    else:
        parts = "(ninguno)"
    click.echo(f"Formatos generados: {parts}")

    click.echo(f"Advertencias: {len(warnings)}")
    for w in warnings[:5]:
        click.echo(f"  • {w}")
    if len(warnings) > 5:
        click.echo(f"  ... y {len(warnings) - 5} más")

    click.echo(f"Errores: {len(errors)}")
    for e in errors[:5]:
        click.echo(f"  • {e}")
    if len(errors) > 5:
        click.echo(f"  ... y {len(errors) - 5} más")

    output_dir = "output/"
    click.echo(f"\nSalida disponible en {output_dir}")
