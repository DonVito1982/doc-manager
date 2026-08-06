"""CLI with Click — entry point for the ``documentos`` command."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import click

from documentos.build.assets import copy_assets
from documentos.build.collector import collect
from documentos.config import ConfigError, init_config, load_config

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


@click.group()
def main():
    """Gestor de documentos para firmas de ingeniería."""


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


@main.command()
def build():
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

    sources = collect(cfg)

    copied = copy_assets(cfg)
    if copied:
        click.echo(f"\nActivos copiados: {len(copied)} archivos")
    else:
        click.echo("\nActivos: (sin activos adicionales — solo empaquetados)")

    if sources:
        for sf in sources:
            click.echo(f"  {sf.path} [{sf.format}]")
    else:
        click.echo("  (no se encontraron archivos fuente en content/)")

    click.echo("\nBuild pipeline no implementado — se listan los archivos encontrados")


@main.command()
def serve():
    """Servidor web (placeholder)."""
    click.echo("Servidor no implementado — disponible en la Fase 3")
