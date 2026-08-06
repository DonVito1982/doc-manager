"""Project configuration module.

Handles loading, validating, and generating the config.yml file that
governs all tool behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ConfigError(Exception):
    """Custom exception for all configuration-related errors."""

    pass


# ---------------------------------------------------------------------------
# Default values (matching the roadmap section 1.3 YAML template)
# ---------------------------------------------------------------------------

DEFAULT_PROJECT_TITLE = "Nombre del Proyecto"
DEFAULT_PROJECT_AUTHOR = "Autor"
DEFAULT_PROJECT_LANGUAGE = "es"

DEFAULT_OUTPUT_FORMATS = ("html", "pdf", "epub")
DEFAULT_OUTPUT_DIR = "output"

DEFAULT_PDF_HEADER = ""
DEFAULT_PDF_FOOTER = ""
DEFAULT_PDF_MATH_FONT = "Latin Modern Math"
DEFAULT_PDF_MATH_FONT_SIZE = 11

DEFAULT_MARKUP = "pandoc-markdown"

DEFAULT_DATA_DIR = "data"

DEFAULT_TEMPLATES_DIR = "templates"
DEFAULT_LAYOUT = "base.html"

DEFAULT_DATABASE_URL = "sqlite:///project.db"

DEFAULT_SERVER_HOST = "127.0.0.1"
DEFAULT_SERVER_PORT = 5000

# Directories that *must* exist on disk (relative to project root)
REQUIRED_DIRECTORIES = ("content", "data", "templates")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ProjectInfo:
    """Metadata about the document project."""

    title: str = DEFAULT_PROJECT_TITLE
    author: str = DEFAULT_PROJECT_AUTHOR
    language: str = DEFAULT_PROJECT_LANGUAGE


@dataclass
class OutputSection:
    """Output format and destination configuration."""

    formats: list[str] = field(default_factory=lambda: list(DEFAULT_OUTPUT_FORMATS))
    dir: str = DEFAULT_OUTPUT_DIR


@dataclass
class PdfSection:
    """PDF generation options (via LaTeX)."""

    header: str = DEFAULT_PDF_HEADER
    footer: str = DEFAULT_PDF_FOOTER
    template: str | None = None
    math_font: str = DEFAULT_PDF_MATH_FONT
    math_font_size: int = DEFAULT_PDF_MATH_FONT_SIZE


@dataclass
class MarkupSection:
    """Source markup format configuration."""

    default: str = DEFAULT_MARKUP


@dataclass
class DataSection:
    """Data files configuration."""

    dir: str = DEFAULT_DATA_DIR
    files: list[str] = field(default_factory=list)


@dataclass
class TemplatesSection:
    """HTML template configuration."""

    dir: str = DEFAULT_TEMPLATES_DIR
    default_layout: str = DEFAULT_LAYOUT


@dataclass
class DatabaseSection:
    """Database connection configuration."""

    url: str = DEFAULT_DATABASE_URL
    data_queries: list[dict] = field(default_factory=list)


@dataclass
class ServerSection:
    """Built-in web server configuration."""

    host: str = DEFAULT_SERVER_HOST
    port: int = DEFAULT_SERVER_PORT


# ---------------------------------------------------------------------------
# Root config container
# ---------------------------------------------------------------------------


@dataclass
class ProjectConfig:
    """Top-level project configuration aggregating all sections.

    Attributes:
        root: Absolute path to the project root directory (the directory
            containing ``config.yml``).  This value is **not** read from the
            YAML file; it is derived from the location of the file on disk.
        project: Project metadata section.
        output: Output section.
        pdf: PDF section.
        markup: Markup section.
        data: Data section.
        templates: Templates section.
        database: Database section.
        server: Server section.
    """

    root: Path = field(default_factory=Path)
    project: ProjectInfo = field(default_factory=ProjectInfo)
    output: OutputSection = field(default_factory=OutputSection)
    pdf: PdfSection = field(default_factory=PdfSection)
    markup: MarkupSection = field(default_factory=MarkupSection)
    data: DataSection = field(default_factory=DataSection)
    templates: TemplatesSection = field(default_factory=TemplatesSection)
    database: DatabaseSection = field(default_factory=DatabaseSection)
    server: ServerSection = field(default_factory=ServerSection)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_config(path: Path) -> ProjectConfig:
    """Load, parse and validate a ``config.yml`` file.

    Args:
        path: Filesystem path to the ``config.yml`` file.

    Returns:
        A fully-populated ``ProjectConfig`` instance.

    Raises:
        ConfigError: If the file is missing, the YAML is malformed, required
            directories are absent, or validation of the parsed data fails.
    """
    if not path.is_file():
        raise ConfigError(f"Configuration file not found: {path}")

    # Parse YAML ----------------------------------------------------------------
    try:
        raw_text = path.read_text(encoding="utf-8")
        raw_data: dict = yaml.safe_load(raw_text) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Failed to parse YAML in {path}: {exc}") from exc

    if not isinstance(raw_data, dict):
        raise ConfigError(
            f"Expected a YAML mapping at the top level of {path}, "
            f"got {type(raw_data).__name__}"
        )

    # Determine project root ----------------------------------------------------
    project_root = path.parent.resolve()

    # Build nested dataclasses (applying defaults for missing keys) -------------
    project_section = _parse_project(raw_data.get("project"))
    output_section = _parse_output(raw_data.get("output"))
    pdf_section = _parse_pdf(raw_data.get("pdf"))
    markup_section = _parse_markup(raw_data.get("markup"))
    data_section = _parse_data(raw_data.get("data"))
    templates_section = _parse_templates(raw_data.get("templates"))
    database_section = _parse_database(raw_data.get("database"))
    server_section = _parse_server(raw_data.get("server"))

    config = ProjectConfig(
        root=project_root,
        project=project_section,
        output=output_section,
        pdf=pdf_section,
        markup=markup_section,
        data=data_section,
        templates=templates_section,
        database=database_section,
        server=server_section,
    )

    # Validate ------------------------------------------------------------------
    _validate_output_formats(config.output.formats)
    _validate_directories(project_root)

    return config


def init_config(path: Path) -> ProjectConfig:
    """Generate a ``config.yml`` file populated with default values.

    The generated file is written to *path* and the corresponding
    ``ProjectConfig`` instance is returned.

    Args:
        path: Desired filesystem location for the new ``config.yml``.

    Returns:
        A ``ProjectConfig`` instance reflecting the default settings.
    """
    config = ProjectConfig()
    config.root = path.parent.resolve()
    _write_config_yaml(path, config)
    return config


# ---------------------------------------------------------------------------
# Internal helpers — parsing
# ---------------------------------------------------------------------------


def _parse_project(raw: dict | None) -> ProjectInfo:
    if not isinstance(raw, dict):
        return ProjectInfo()
    return ProjectInfo(
        title=str(raw.get("title", DEFAULT_PROJECT_TITLE)),
        author=str(raw.get("author", DEFAULT_PROJECT_AUTHOR)),
        language=str(raw.get("language", DEFAULT_PROJECT_LANGUAGE)),
    )


def _parse_output(raw: dict | None) -> OutputSection:
    if not isinstance(raw, dict):
        return OutputSection()
    formats = raw.get("formats", list(DEFAULT_OUTPUT_FORMATS))
    if not isinstance(formats, list):
        formats = list(DEFAULT_OUTPUT_FORMATS)
    else:
        formats = [str(f) for f in formats]
    return OutputSection(
        formats=formats,
        dir=str(raw.get("dir", DEFAULT_OUTPUT_DIR)),
    )


def _parse_pdf(raw: dict | None) -> PdfSection:
    if not isinstance(raw, dict):
        return PdfSection()
    template = raw.get("template", None)
    math_font_size = raw.get("math_font_size", DEFAULT_PDF_MATH_FONT_SIZE)
    return PdfSection(
        header=str(raw.get("header", DEFAULT_PDF_HEADER)),
        footer=str(raw.get("footer", DEFAULT_PDF_FOOTER)),
        template=str(template) if template is not None else None,
        math_font=str(raw.get("math_font", DEFAULT_PDF_MATH_FONT)),
        math_font_size=int(math_font_size)
        if math_font_size is not None
        else DEFAULT_PDF_MATH_FONT_SIZE,
    )


def _parse_markup(raw: dict | None) -> MarkupSection:
    if not isinstance(raw, dict):
        return MarkupSection()
    return MarkupSection(
        default=str(raw.get("default", DEFAULT_MARKUP)),
    )


def _parse_data(raw: dict | None) -> DataSection:
    if not isinstance(raw, dict):
        return DataSection()
    files = raw.get("files", [])
    if not isinstance(files, list):
        files = []
    return DataSection(
        dir=str(raw.get("dir", DEFAULT_DATA_DIR)),
        files=[str(f) for f in files],
    )


def _parse_templates(raw: dict | None) -> TemplatesSection:
    if not isinstance(raw, dict):
        return TemplatesSection()
    return TemplatesSection(
        dir=str(raw.get("dir", DEFAULT_TEMPLATES_DIR)),
        default_layout=str(raw.get("default_layout", DEFAULT_LAYOUT)),
    )


def _parse_database(raw: dict | None) -> DatabaseSection:
    if not isinstance(raw, dict):
        return DatabaseSection()
    queries = raw.get("data_queries", [])
    if not isinstance(queries, list):
        queries = []
    else:
        queries = [
            {"alias": str(q["alias"]), "sql": str(q["sql"])}
            for q in queries
            if isinstance(q, dict) and "alias" in q and "sql" in q
        ]
    return DatabaseSection(
        url=str(raw.get("url", DEFAULT_DATABASE_URL)),
        data_queries=queries,
    )


def _parse_server(raw: dict | None) -> ServerSection:
    if not isinstance(raw, dict):
        return ServerSection()
    return ServerSection(
        host=str(raw.get("host", DEFAULT_SERVER_HOST)),
        port=int(raw.get("port", DEFAULT_SERVER_PORT)),
    )


# ---------------------------------------------------------------------------
# Internal helpers — validation
# ---------------------------------------------------------------------------

VALID_FORMATS = frozenset({"html", "pdf", "epub"})


def _validate_output_formats(formats: list[str]) -> None:
    """Validate the ``output.formats`` list.

    Raises:
        ConfigError: If the list is empty or contains an unsupported format.
    """
    if not formats:
        raise ConfigError(
            "output.formats cannot be empty. "
            f"Supported formats: {sorted(VALID_FORMATS)}"
        )
    invalid = [f for f in formats if f not in VALID_FORMATS]
    if invalid:
        raise ConfigError(
            f"Unsupported output format(s): {invalid}. "
            f"Supported formats: {sorted(VALID_FORMATS)}"
        )


def _validate_directories(project_root: Path) -> None:
    """Ensure required directories exist relative to *project_root*.

    Raises:
        ConfigError: If any required directory is missing.
    """
    missing: list[str] = []
    for dirname in REQUIRED_DIRECTORIES:
        dir_path = project_root / dirname
        if not dir_path.is_dir():
            missing.append(dirname)
    if missing:
        raise ConfigError(
            f"Missing required directorie(s) in {project_root}: {', '.join(missing)}"
        )


# ---------------------------------------------------------------------------
# Internal helpers — serialisation
# ---------------------------------------------------------------------------


def _config_to_dict(config: ProjectConfig) -> dict:
    """Convert a *ProjectConfig* instance to a plain dict suitable for
    serialising to YAML.

    The ``root`` attribute is intentionally excluded because it is not a YAML
    field.
    """
    return {
        "project": {
            "title": config.project.title,
            "author": config.project.author,
            "language": config.project.language,
        },
        "output": {
            "formats": config.output.formats,
            "dir": config.output.dir,
        },
        "pdf": {
            "header": config.pdf.header,
            "footer": config.pdf.footer,
            "template": config.pdf.template,
            "math_font": config.pdf.math_font,
            "math_font_size": config.pdf.math_font_size,
        },
        "markup": {
            "default": config.markup.default,
        },
        "data": {
            "dir": config.data.dir,
            "files": config.data.files,
        },
        "templates": {
            "dir": config.templates.dir,
            "default_layout": config.templates.default_layout,
        },
        "database": {
            "url": config.database.url,
            "data_queries": config.database.data_queries,
        },
        "server": {
            "host": config.server.host,
            "port": config.server.port,
        },
    }


def _write_config_yaml(path: Path, config: ProjectConfig) -> None:
    """Serialize *config* to *path* as YAML."""
    data = _config_to_dict(config)
    with path.open("w", encoding="utf-8") as fh:
        yaml.dump(
            data,
            fh,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
