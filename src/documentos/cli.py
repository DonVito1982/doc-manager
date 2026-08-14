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

    # Create default asset directories with sensible defaults
    _write_init_assets(project_path)

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
# Internal — asset generation for init
# ---------------------------------------------------------------------------

_DEFAULT_CSS = """\
/* =====================================================================
   Base styles for the documentation site generated by gestor-v2.
   Clean, functional, responsive — no external frameworks.
   ===================================================================== */

/* --- Reset & box-sizing ------------------------------------------------ */

*,
*::before,
*::after {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

/* --- Typography -------------------------------------------------------- */

body {
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, Oxygen,
        Ubuntu, Cantarell, "Helvetica Neue", Arial, sans-serif;
    font-size: 16px;
    line-height: 1.6;
    color: #2d2d2d;
    background-color: #fafafa;
}

h1, h2, h3, h4, h5, h6 {
    font-weight: 600;
    line-height: 1.3;
    color: #1a1a1a;
    margin-bottom: 0.5em;
}

h1 { font-size: 2rem; }
h2 { font-size: 1.5rem; }
h3 { font-size: 1.25rem; }
h4 { font-size: 1.1rem; }

p {
    margin-bottom: 1em;
}

a {
    color: #2563eb;
    text-decoration: none;
}

a:hover {
    text-decoration: underline;
}

code {
    font-family: "Fira Code", "Cascadia Code", Consolas, monospace;
    font-size: 0.9em;
    background-color: #f0f0f0;
    padding: 0.1em 0.3em;
    border-radius: 3px;
}

pre {
    background-color: #f0f0f0;
    padding: 1em;
    border-radius: 4px;
    overflow-x: auto;
    margin-bottom: 1em;
}

pre code {
    background: none;
    padding: 0;
}

/* --- Layout ------------------------------------------------------------ */

body {
    display: flex;
    flex-direction: column;
    min-height: 100vh;
}

header {
    background-color: #1e293b;
    color: #f8fafc;
    padding: 1rem 2rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
}

header h1 {
    color: #f8fafc;
    font-size: 1.25rem;
    margin-bottom: 0;
}

main {
    display: flex;
    flex: 1;
    max-width: 1200px;
    width: 100%;
    margin: 0 auto;
    padding: 1.5rem 1rem;
    gap: 2rem;
}

article.content {
    flex: 1;
    min-width: 0;
    max-width: 48rem;
}

footer {
    background-color: #1e293b;
    color: #94a3b8;
    text-align: center;
    padding: 1rem 2rem;
    font-size: 0.875rem;
}

/* --- Navigation -------------------------------------------------------- */

.site-nav a {
    color: #93c5fd;
    font-weight: 500;
}

.site-nav a:hover {
    color: #bfdbfe;
    text-decoration: none;
}

/* --- Sidebar ----------------------------------------------------------- */

.sidebar {
    width: 240px;
    flex-shrink: 0;
    border-right: 1px solid #e2e8f0;
    padding-right: 1rem;
}

.sidebar h2 {
    font-size: 1rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #64748b;
    margin-bottom: 0.75rem;
}

.sidebar ul {
    list-style: none;
}

.sidebar li {
    margin-bottom: 0.4rem;
}

.sidebar a {
    color: #475569;
    font-size: 0.9rem;
    display: block;
    padding: 0.2rem 0;
}

.sidebar a:hover {
    color: #2563eb;
    text-decoration: none;
}

/* --- Responsive -------------------------------------------------------- */

@media (max-width: 768px) {
    main {
        flex-direction: column;
        padding: 1rem;
    }

    .sidebar {
        width: 100%;
        border-right: none;
        border-bottom: 1px solid #e2e8f0;
        padding-right: 0;
        padding-bottom: 1rem;
        margin-bottom: 1rem;
    }

    header {
        padding: 1rem;
    }

    header h1 {
        font-size: 1.1rem;
    }
}

@media (max-width: 480px) {
    body {
        font-size: 15px;
    }

    h1 { font-size: 1.5rem; }
    h2 { font-size: 1.25rem; }
}
"""

_DEFAULT_MATHJAX_CONFIG = """\
MathJax = {
    tex: {
        inlineMath: [["$", "$"], ["\\\\(", "\\\\)"]],
        displayMath: [["$$", "$$"], ["\\\\[", "\\\\]"]],
        processEscapes: true,
        tags: "ams",
    },
};
"""


def _write_init_assets(project_path: Path) -> None:
    """Write default CSS and JavaScript assets into the project.

    Creates ``templates/assets/css/style.css`` and
    ``templates/assets/js/mathjax-config.js`` with sensible defaults that
    the user can customize later.

    Args:
        project_path: The project root directory.
    """
    assets_dir = project_path / "templates" / "assets"
    css_dir = assets_dir / "css"
    js_dir = assets_dir / "js"
    css_dir.mkdir(parents=True, exist_ok=True)
    js_dir.mkdir(parents=True, exist_ok=True)

    (css_dir / "style.css").write_text(_DEFAULT_CSS, encoding="utf-8")
    (js_dir / "mathjax-config.js").write_text(_DEFAULT_MATHJAX_CONFIG, encoding="utf-8")


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
